/**
 * imageAttachment.ts — turn pasted / uploaded image files into PageAttachments.
 *
 * Images are downscaled to MAX_IMAGE_DIM on the long edge and re-encoded so the
 * base64 data URL stays small over the runtime message + WebSocket hop. The
 * bridge parses the data URL into a real Claude image content block.
 */
import type { PageAttachment } from '@/shared/frames';

/** Claude handles images best at ≤1568px on the long edge; downscale to that. */
const MAX_IMAGE_DIM = 1568;
/** Skip files larger than this (pre-downscale) to avoid janking the panel. */
const MAX_SOURCE_BYTES = 12 * 1024 * 1024;

export function isImageFile(file: File | null | undefined): boolean {
  return Boolean(file && file.type.startsWith('image/'));
}

/** Pull image files out of a clipboard/drag DataTransfer, if any. */
export function imageFilesFromDataTransfer(dt: DataTransfer | null): File[] {
  if (!dt) return [];
  const out: File[] = [];
  for (const item of Array.from(dt.items || [])) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      const file = item.getAsFile();
      if (file) out.push(file);
    }
  }
  if (out.length === 0) {
    for (const file of Array.from(dt.files || [])) {
      if (isImageFile(file)) out.push(file);
    }
  }
  return out;
}

async function fileToDownscaledDataUrl(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_IMAGE_DIM / Math.max(bitmap.width, bitmap.height));
  const dw = Math.max(1, Math.round(bitmap.width * scale));
  const dh = Math.max(1, Math.round(bitmap.height * scale));
  const canvas = new OffscreenCanvas(dw, dh);
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    bitmap.close();
    return readAsDataUrl(file);
  }
  ctx.drawImage(bitmap, 0, 0, dw, dh);
  bitmap.close();
  // PNG keeps text/screenshots crisp; transparency is preserved too.
  const blob = await canvas.convertToBlob({ type: 'image/png' });
  return readAsDataUrl(blob);
}

function readAsDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/** Build an image PageAttachment from a file, or null if it can't be read. */
export async function fileToImageAttachment(file: File): Promise<PageAttachment | null> {
  if (!isImageFile(file) || file.size > MAX_SOURCE_BYTES) return null;
  try {
    const dataUrl = await fileToDownscaledDataUrl(file);
    return {
      kind: 'image',
      label: file.name || 'Pasted image',
      data: dataUrl,
    };
  } catch {
    return null;
  }
}
