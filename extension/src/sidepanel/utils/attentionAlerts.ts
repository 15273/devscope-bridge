/**
 * attentionAlerts.ts — sound, title flash, and desktop notifications when input is needed.
 */

let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  try {
    if (!audioCtx) audioCtx = new AudioContext();
    if (audioCtx.state === 'suspended') void audioCtx.resume();
    return audioCtx;
  } catch {
    return null;
  }
}

/** Short two-tone chime (no file / permission required). */
export function playAttentionChime(): void {
  const ctx = getAudioContext();
  if (!ctx) return;

  const playTone = (freq: number, start: number, duration: number) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.12, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(start);
    osc.stop(start + duration);
  };

  const t = ctx.currentTime;
  playTone(880, t, 0.14);
  playTone(1174.66, t + 0.16, 0.18);
}

export function startTitleFlash(prefix: string): () => void {
  const base = document.title.replace(/^●\s*/, '');
  let on = true;
  document.title = `${prefix} ${base}`;

  const id = window.setInterval(() => {
    on = !on;
    document.title = on ? `${prefix} ${base}` : base;
  }, 900);

  return () => {
    clearInterval(id);
    document.title = base;
  };
}

export async function ensureNotificationPermission(): Promise<boolean> {
  if (!chrome.notifications?.create) return false;
  if (Notification.permission === 'granted') return true;
  if (Notification.permission === 'denied') return false;
  try {
    const perm = await Notification.requestPermission();
    return perm === 'granted';
  } catch {
    return false;
  }
}

export async function showAttentionNotification(
  sessionName: string,
  body: string,
): Promise<void> {
  if (!chrome.notifications?.create) return;
  const id = `devscope-attention-${sessionName}-${Date.now()}`;
  try {
    await chrome.notifications.create(id, {
      type: 'basic',
      iconUrl: chrome.runtime.getURL('icon-128.png'),
      title: `DevScope — ${sessionName}`,
      message: body,
      priority: 2,
    });
  } catch {
    /* ignore — permission may be missing */
  }
}
