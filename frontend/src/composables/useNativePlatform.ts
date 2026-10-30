import { ref, computed } from 'vue';
import { Capacitor } from '@capacitor/core';
import { Haptics, ImpactStyle, NotificationType } from '@capacitor/haptics';
import { StatusBar, Style } from '@capacitor/status-bar';
import { Share } from '@capacitor/share';

const isNative = ref(Capacitor.isNativePlatform());
const currentPlatform = ref(Capacitor.getPlatform()); // 'ios' | 'android' | 'web'
const mqlMobile = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(max-width: 768px)') : null;
const isMobileViewport = ref(mqlMobile ? mqlMobile.matches : false);
export const isMobileImmersiveMode = ref(false);
export const mobileWorkspaceTab = ref<'library' | 'create'>('library');
export const activeProcessingCount = ref(0);

// Track breakpoint changes without polling window.innerWidth / forcing reflow
if (mqlMobile) {
  mqlMobile.addEventListener('change', (e) => {
    isMobileViewport.value = e.matches;
  });
}

export function useNativePlatform() {
  const isMobile = computed(() => isNative.value || isMobileViewport.value);

  // Trigger light tactile feedback on UI taps
  async function triggerHapticLight() {
    if (!isNative.value) return;
    try {
      await Haptics.impact({ style: ImpactStyle.Light });
    } catch {
      // Ignore if not supported on platform
    }
  }

  // Trigger medium tactile feedback (e.g. measure selection, tempo tap)
  async function triggerHapticMedium() {
    if (!isNative.value) return;
    try {
      await Haptics.impact({ style: ImpactStyle.Medium });
    } catch {
      // Ignore
    }
  }

  // Trigger success vibration (e.g. OMR transcription complete)
  async function triggerHapticSuccess() {
    if (!isNative.value) return;
    try {
      await Haptics.notification({ type: NotificationType.Success });
    } catch {
      // Ignore
    }
  }

  // Trigger error vibration
  async function triggerHapticError() {
    if (!isNative.value) return;
    try {
      await Haptics.notification({ type: NotificationType.Error });
    } catch {
      // Ignore
    }
  }

  // Configure status bar according to theme
  async function setStatusBarStyle(isDark: boolean, bgColor?: string) {
    if (!isNative.value) return;
    try {
      await StatusBar.setStyle({ style: isDark ? Style.Dark : Style.Light });
      if (currentPlatform.value === 'android') {
        await StatusBar.setBackgroundColor({ color: bgColor || (isDark ? '#0c0f17' : '#f8fafc') });
      }
    } catch {
      // Ignore
    }
  }

  // Native share sheet
  async function shareContent(title: string, text: string, url: string): Promise<boolean> {
    try {
      if (isNative.value) {
        const canShare = await Share.canShare();
        if (canShare.value) {
          await Share.share({ title, text, url, dialogTitle: title });
          return true;
        }
      } else if (navigator.share) {
        await navigator.share({ title, text, url });
        return true;
      }
    } catch {
      // Share dismissed or unsupported
    }
    return false;
  }

  return {
    isNative,
    isMobile,
    isMobileImmersiveMode,
    mobileWorkspaceTab,
    activeProcessingCount,
    platform: currentPlatform,
    triggerHapticLight,
    triggerHapticMedium,
    triggerHapticSuccess,
    triggerHapticError,
    setStatusBarStyle,
    shareContent,
  };
}
