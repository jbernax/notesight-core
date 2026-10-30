/**
 * Lightweight client-side JPEG to multi-page PDF generator.
 * Packages multiple captured sheet music photos into a standard PDF without external dependencies.
 */

interface ImageDimensions {
  width: number;
  height: number;
}

/**
 * Extracts width and height from JPEG bytes (reading SOF0/SOF2 markers).
 */
export async function getJpegDimensions(blob: Blob): Promise<ImageDimensions> {
  const buffer = await blob.arrayBuffer();
  const view = new DataView(buffer);

  // Check JPEG SOI marker 0xFFD8
  if (view.getUint16(0) !== 0xffd8) {
    return { width: 1200, height: 1600 }; // fallback default aspect ratio
  }

  let offset = 2;
  while (offset < view.byteLength) {
    const marker = view.getUint16(offset);
    offset += 2;

    // SOF0 (0xFFC0) or SOF2 (0xFFC2) contain dimensions
    if (marker === 0xffc0 || marker === 0xffc2) {
      const height = view.getUint16(offset + 3);
      const width = view.getUint16(offset + 5);
      return { width, height };
    }

    // Skip variable-length marker segment
    if (offset + 2 > view.byteLength) break;
    const length = view.getUint16(offset);
    offset += length;
  }

  return { width: 1200, height: 1600 };
}

/**
 * Compiles an array of JPEG blobs into a single multi-page PDF Blob.
 */
export async function compileJpegsToPdf(jpegBlobs: Blob[]): Promise<Blob> {
  const pagesData: {
    dimensions: ImageDimensions;
    bytes: Uint8Array;
  }[] = [];

  for (const blob of jpegBlobs) {
    const dimensions = await getJpegDimensions(blob);
    const buffer = await blob.arrayBuffer();
    pagesData.push({
      dimensions,
      bytes: new Uint8Array(buffer),
    });
  }

  const parts: (Uint8Array | string)[] = [];
  const offsets: number[] = [];
  let currentOffset = 0;

  function writeString(str: string) {
    const encoder = new TextEncoder();
    const bytes = encoder.encode(str);
    parts.push(bytes);
    currentOffset += bytes.length;
  }

  function writeBytes(bytes: Uint8Array) {
    parts.push(bytes);
    currentOffset += bytes.length;
  }

  // Header
  writeString('%PDF-1.4\n%âãÏÓ\n');

  // Object 1: Catalog
  offsets.push(currentOffset);
  writeString('1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n');

  const pageCount = pagesData.length;
  const pageObjStart = 3;
  const kidsRefs: string[] = [];
  for (let i = 0; i < pageCount; i++) {
    // Each page takes 3 objects: Page, Content stream, Image XObject
    const pageObjNum = pageObjStart + i * 3;
    kidsRefs.push(`${pageObjNum} 0 R`);
  }

  // Object 2: Pages root
  offsets.push(currentOffset);
  writeString(`2 0 obj\n<< /Type /Pages /Kids [ ${kidsRefs.join(' ')} ] /Count ${pageCount} >>\nendobj\n`);

  for (let i = 0; i < pageCount; i++) {
    const pageNum = i + 1;
    const pageObjNum = pageObjStart + i * 3;
    const contentObjNum = pageObjNum + 1;
    const imageObjNum = pageObjNum + 2;
    const { dimensions, bytes } = pagesData[i];
    const w = dimensions.width;
    const h = dimensions.height;

    // Page object
    offsets.push(currentOffset);
    writeString(
      `${pageObjNum} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [ 0 0 ${w} ${h} ] /Resources << /XObject << /Im${pageNum} ${imageObjNum} 0 R >> >> /Contents ${contentObjNum} 0 R >>\nendobj\n`
    );

    // Content stream: scale image to page MediaBox dimensions
    const contentStream = `q\n${w} 0 0 ${h} 0 0 cm\n/Im${pageNum} Do\nQ\n`;
    const contentStreamBytes = new TextEncoder().encode(contentStream);

    offsets.push(currentOffset);
    writeString(
      `${contentObjNum} 0 obj\n<< /Length ${contentStreamBytes.length} >>\nstream\n`
    );
    writeBytes(contentStreamBytes);
    writeString('endstream\nendobj\n');

    // Image XObject (embed raw JPEG directly)
    offsets.push(currentOffset);
    writeString(
      `${imageObjNum} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${w} /Height ${h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${bytes.length} >>\nstream\n`
    );
    writeBytes(bytes);
    writeString('\nendstream\nendobj\n');
  }

  // Cross-reference table (xref)
  const xrefOffset = currentOffset;
  const totalObjects = 1 + 2 + pageCount * 3;
  writeString(`xref\n0 ${totalObjects}\n0000000000 65535 f \n`);
  for (const offset of offsets) {
    writeString(`${offset.toString().padStart(10, '0')} 00000 n \n`);
  }

  // Trailer
  writeString(
    `trailer\n<< /Size ${totalObjects} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`
  );

  return new Blob(parts as any[], { type: 'application/pdf' });
}
