/**
 * elementScreenshot.ts — crop/compress captures from captureVisibleTab.
 */

interface BBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Full-page captures are downscaled so MV3 message + WS payloads stay small. */
const MAX_FULL_CAPTURE_WIDTH = 1280;

/**
 * Service workers have no FileReader, so we base64-encode by hand — but in
 * 32KB chunks via String.fromCharCode.apply, not byte-by-byte. Per-byte string
 * concatenation is O(n²) (strings are immutable) and stalls for several seconds
 * on a 200–500KB capture, which is what made browser_screenshot appear to hang.
 */
const BASE64_CHUNK_SIZE = 0x8000;

async function blobToDataUrl(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += BASE64_CHUNK_SIZE) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + BASE64_CHUNK_SIZE) as unknown as number[]);
  }
  return `data:${blob.type};base64,${btoa(binary)}`;
}

async function getDevicePixelRatio(tabId: number): Promise<number> {
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => window.devicePixelRatio || 1,
    });
    const dpr = result?.result;
    return typeof dpr === 'number' && dpr > 0 ? dpr : 1;
  } catch {
    return 1;
  }
}

/** Downscale + re-encode a tab capture (avoids multi-MB PNG over runtime/WS). */
export async function compressFullPageCapture(dataUrl: string): Promise<string> {
  try {
    const response = await fetch(dataUrl);
    const blob = await response.blob();
    const bitmap = await createImageBitmap(blob);
    const scale = Math.min(1, MAX_FULL_CAPTURE_WIDTH / bitmap.width);
    const dw = Math.max(1, Math.round(bitmap.width * scale));
    const dh = Math.max(1, Math.round(bitmap.height * scale));

    const canvas = new OffscreenCanvas(dw, dh);
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      bitmap.close();
      return dataUrl;
    }
    ctx.drawImage(bitmap, 0, 0, dw, dh);
    bitmap.close();

    const out = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.78 });
    return blobToDataUrl(out);
  } catch {
    return dataUrl;
  }
}

/** Capture a small JPEG thumbnail of the element region (viewport coords). */
export async function captureElementSnippet(
  tabId: number,
  windowId: number,
  bbox: BBox,
): Promise<string | undefined> {
  if (bbox.width <= 0 || bbox.height <= 0) return undefined;
  try {
    const dataUrl = await chrome.tabs.captureVisibleTab(windowId, {
      format: 'jpeg',
      quality: 72,
    });
    const dpr = await getDevicePixelRatio(tabId);
    const response = await fetch(dataUrl);
    const blob = await response.blob();
    const bitmap = await createImageBitmap(blob);

    const pad = 6;
    const sx = Math.max(0, Math.floor(bbox.x * dpr) - pad);
    const sy = Math.max(0, Math.floor(bbox.y * dpr) - pad);
    const sw = Math.min(bitmap.width - sx, Math.ceil(bbox.width * dpr) + pad * 2);
    const sh = Math.min(bitmap.height - sy, Math.ceil(bbox.height * dpr) + pad * 2);
    if (sw <= 0 || sh <= 0) {
      bitmap.close();
      return undefined;
    }

    const maxDim = 128;
    const scale = Math.min(1, maxDim / Math.max(sw, sh));
    const dw = Math.max(1, Math.round(sw * scale));
    const dh = Math.max(1, Math.round(sh * scale));

    const canvas = new OffscreenCanvas(dw, dh);
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      bitmap.close();
      return undefined;
    }
    ctx.drawImage(bitmap, sx, sy, sw, sh, 0, 0, dw, dh);
    bitmap.close();

    const out = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.78 });
    return blobToDataUrl(out);
  } catch {
    return undefined;
  }
}
