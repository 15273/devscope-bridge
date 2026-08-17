import { getSpeechRecognitionCtor } from '@/shared/speech/speechRecognition';

const grantBtn = document.getElementById('grant') as HTMLButtonElement | null;
const statusEl = document.getElementById('status');

function setStatus(text: string, ok: boolean): void {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.className = ok ? 'ok' : 'err';
}

grantBtn?.addEventListener('click', async () => {
  if (!grantBtn) return;
  grantBtn.disabled = true;
  setStatus('מבקש הרשאה…', true);

  try {
    if (navigator.mediaDevices?.getUserMedia) {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      for (const track of stream.getTracks()) track.stop();
    }

    const Ctor = getSpeechRecognitionCtor();
    if (Ctor) {
      await new Promise<void>((resolve, reject) => {
        const rec = new Ctor();
        rec.lang = navigator.language || 'he-IL';
        rec.continuous = false;
        rec.interimResults = false;
        const timer = window.setTimeout(() => {
          try {
            rec.stop();
          } catch {
            /* ignore */
          }
          resolve();
        }, 1200);
        rec.onstart = () => {
          window.clearTimeout(timer);
          window.setTimeout(() => {
            try {
              rec.stop();
            } catch {
              /* ignore */
            }
            resolve();
          }, 400);
        };
        rec.onerror = (e) => {
          window.clearTimeout(timer);
          const code = (e as { error?: string }).error ?? 'unknown';
          if (code === 'not-allowed' || code === 'service-not-allowed') {
            reject(new Error(code));
            return;
          }
          resolve();
        };
        try {
          rec.start();
        } catch (err) {
          window.clearTimeout(timer);
          reject(err);
        }
      });
    }

    await chrome.storage.local.set({ micGranted: true });
    setStatus('המיקרופון הופעל — חזור ל-DevScope ולחץ על אייקון המיקרופון ליד Send.', true);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    setStatus(
      `נכשל: ${msg}. Chrome → Extensions → DevScope → Site settings → Microphone → Allow.`,
      false,
    );
    grantBtn.disabled = false;
  }
});
