/** Bridge transcode: WebM tab recording → MP4 (requires local ffmpeg). */

const BRIDGE_BASE = 'http://127.0.0.1:7878';
const TRANSCODE_TIMEOUT_MS = 120_000;

export async function transcodeWebmToMp4(webm: Blob, token: string): Promise<Blob> {
  const form = new FormData();
  form.append('file', webm, 'recording.webm');
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  const resp = await fetch(`${BRIDGE_BASE}/recordings/to-mp4`, {
    method: 'POST',
    headers,
    body: form,
    signal: AbortSignal.timeout(TRANSCODE_TIMEOUT_MS),
  });

  if (!resp.ok) {
    let detail = '';
    try {
      const body = (await resp.json()) as { detail?: string };
      detail = body.detail ?? '';
    } catch {
      detail = await resp.text().catch(() => '');
    }
    throw new Error(detail || `Transcode failed (HTTP ${resp.status})`);
  }

  return resp.blob();
}
