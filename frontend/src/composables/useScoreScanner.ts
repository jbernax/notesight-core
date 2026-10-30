import { ref } from 'vue';
import { Camera, CameraResultType, CameraSource } from '@capacitor/camera';
import { Capacitor } from '@capacitor/core';
import { compileJpegsToPdf, getJpegDimensions } from '../utils/jpegToPdf';
import { useNativePlatform } from './useNativePlatform';
import { apiFetch } from '../services/apiClient';

export interface ScannedPage {
  id: string;
  blob: Blob;
  previewUrl: string;
  width: number;
  height: number;
  rotation: number;
}

export function useScoreScanner() {
  const { triggerHapticLight, triggerHapticSuccess, triggerHapticError } = useNativePlatform();
  const scannedPages = ref<ScannedPage[]>([]);
  const isCapturing = ref(false);
  const isUploading = ref(false);
  const uploadProgress = ref(0);
  const scannerError = ref<string | null>(null);

  /**
   * Helper to convert data URL or URI to Blob
   */
  async function uriToBlob(uri: string): Promise<Blob> {
    const res = await fetch(uri);
    return await res.blob();
  }

  /**
   * Capture a page using Capacitor Camera or native file picker
   */
  async function capturePhoto(source: 'camera' | 'photos' = 'camera'): Promise<boolean> {
    isCapturing.value = true;
    scannerError.value = null;

    try {
      if (Capacitor.isNativePlatform()) {
        const photo = await Camera.getPhoto({
          quality: 90,
          allowEditing: false,
          resultType: CameraResultType.Uri,
          source: source === 'camera' ? CameraSource.Camera : CameraSource.Photos,
        });

        if (photo.webPath) {
          const blob = await uriToBlob(photo.webPath);
          await addBlob(blob);
          await triggerHapticLight();
          return true;
        }
      } else {
        // Fallback for browser / PWA: open input file picker
        return new Promise((resolve) => {
          const input = document.createElement('input');
          input.type = 'file';
          input.accept = 'image/jpeg,image/png,image/webp,image/*';
          if (source === 'camera') {
            input.capture = 'environment';
          }
          input.onchange = async () => {
            if (input.files && input.files.length > 0) {
              for (let i = 0; i < input.files.length; i++) {
                await addBlob(input.files[i]);
              }
              await triggerHapticLight();
              resolve(true);
            } else {
              resolve(false);
            }
          };
          input.oncancel = () => resolve(false);
          input.click();
        });
      }
    } catch (err: any) {
      if (err.message !== 'User cancelled photos app') {
        scannerError.value = err.message || 'Failed to capture photo';
        await triggerHapticError();
      }
      return false;
    } finally {
      isCapturing.value = false;
    }
    return false;
  }

  /**
   * Add a raw image blob to the scan queue
   */
  async function addBlob(blob: Blob): Promise<void> {
    const dims = await getJpegDimensions(blob);
    const previewUrl = URL.createObjectURL(blob);
    scannedPages.value.push({
      id: `page_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      blob,
      previewUrl,
      width: dims.width,
      height: dims.height,
      rotation: 0,
    });
  }

  /**
   * Remove a scanned page
   */
  function removePage(index: number) {
    if (index >= 0 && index < scannedPages.value.length) {
      const page = scannedPages.value[index];
      URL.revokeObjectURL(page.previewUrl);
      scannedPages.value.splice(index, 1);
      triggerHapticLight();
    }
  }

  /**
   * Rotate a scanned page 90 degrees clockwise
   */
  async function rotatePage(index: number) {
    if (index < 0 || index >= scannedPages.value.length) return;
    const page = scannedPages.value[index];
    page.rotation = (page.rotation + 90) % 360;

    // Redraw rotated image onto a canvas to update blob
    const img = new Image();
    img.src = page.previewUrl;
    await new Promise((resolve) => {
      img.onload = resolve;
    });

    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    if (page.rotation === 90 || page.rotation === 270) {
      canvas.width = img.height;
      canvas.height = img.width;
    } else {
      canvas.width = img.width;
      canvas.height = img.height;
    }

    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate((page.rotation * Math.PI) / 180);
    ctx.drawImage(img, -img.width / 2, -img.height / 2);

    const rotatedBlob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.92)
    );

    if (rotatedBlob) {
      URL.revokeObjectURL(page.previewUrl);
      page.blob = rotatedBlob;
      page.previewUrl = URL.createObjectURL(rotatedBlob);
      page.width = canvas.width;
      page.height = canvas.height;
      page.rotation = 0;
      await triggerHapticLight();
    }
  }

  /**
   * Clear all scanned pages
   */
  function clearPages() {
    scannedPages.value.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    scannedPages.value = [];
    scannerError.value = null;
  }

  /**
   * Compile pages into an upload-ready File (single JPEG if 1 page, multi-page PDF if >1)
   */
  async function generateUploadFile(scoreTitle: string = 'Scanned Score'): Promise<File | null> {
    if (scannedPages.value.length === 0) return null;

    const sanitizedTitle = scoreTitle.trim().replace(/[^a-zA-Z0-9_-]/g, '_') || 'Scanned_Score';

    if (scannedPages.value.length === 1) {
      const page = scannedPages.value[0];
      return new File([page.blob], `${sanitizedTitle}.jpg`, { type: 'image/jpeg' });
    }

    // Multi-page: compile into standard PDF
    const blobs = scannedPages.value.map((p) => p.blob);
    const pdfBlob = await compileJpegsToPdf(blobs);
    return new File([pdfBlob], `${sanitizedTitle}.pdf`, { type: 'application/pdf' });
  }

  /**
   * Upload scanned score to NoteSight backend
   */
  async function uploadAndProcess(scoreTitle?: string): Promise<any> {
    const file = await generateUploadFile(scoreTitle);
    if (!file) throw new Error('No pages scanned');

    isUploading.value = true;
    uploadProgress.value = 10;
    scannerError.value = null;

    try {
      const formData = new FormData();
      formData.append('file', file);

      uploadProgress.value = 40;

      const res = await apiFetch('/api/upload', {
        method: 'POST',
        body: formData,
      });

      uploadProgress.value = 80;

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || `Upload failed (${res.status})`);
      }

      const jobData = await res.json();
      uploadProgress.value = 100;
      await triggerHapticSuccess();
      return jobData;
    } catch (err: any) {
      scannerError.value = err.message || 'Upload failed';
      await triggerHapticError();
      throw err;
    } finally {
      isUploading.value = false;
    }
  }

  return {
    scannedPages,
    isCapturing,
    isUploading,
    uploadProgress,
    scannerError,
    capturePhoto,
    addBlob,
    removePage,
    rotatePage,
    clearPages,
    generateUploadFile,
    uploadAndProcess,
  };
}
