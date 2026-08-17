/**
 * recording_halo_inject.ts — in-page cursor halo shown while tab recording runs.
 *
 * Tab capture does not include the OS cursor, so the halo (glow + center dot)
 * is the only cursor indicator in the recorded video. Clicks spawn an expanding
 * ripple ring. Self-contained for executeScript.
 */

/** Installed in the top frame; long-lived until cleanup. */
export function recordingHaloInjected(): void {
  const HALO_ID = 'devscope-recording-halo';
  const STYLE_ID = 'devscope-recording-halo-style';
  const HALO_SIZE = 56;
  const DOT_SIZE = 10;
  const RIPPLE_SIZE = 72;
  const GLOW = 'rgba(255, 196, 0, 0.35)';
  const RING = 'rgba(255, 160, 0, 0.85)';
  const w = window as unknown as { __dsHaloCleanup?: () => void };

  if (typeof w.__dsHaloCleanup === 'function') {
    try {
      w.__dsHaloCleanup();
    } catch {
      /* re-install after partial teardown */
    }
  }

  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    #${HALO_ID} {
      position: fixed;
      left: 0;
      top: 0;
      width: ${HALO_SIZE}px;
      height: ${HALO_SIZE}px;
      margin: -${HALO_SIZE / 2}px 0 0 -${HALO_SIZE / 2}px;
      border-radius: 50%;
      background: radial-gradient(circle, ${GLOW} 0%, rgba(255, 196, 0, 0.12) 55%, transparent 72%);
      pointer-events: none;
      z-index: 2147483647;
      will-change: transform;
    }
    #${HALO_ID}::after {
      content: '';
      position: absolute;
      left: 50%;
      top: 50%;
      width: ${DOT_SIZE}px;
      height: ${DOT_SIZE}px;
      margin: -${DOT_SIZE / 2}px 0 0 -${DOT_SIZE / 2}px;
      border-radius: 50%;
      background: rgba(255, 140, 0, 0.95);
      box-shadow: 0 0 4px rgba(0, 0, 0, 0.4);
    }
    .devscope-recording-ripple {
      position: fixed;
      width: ${RIPPLE_SIZE}px;
      height: ${RIPPLE_SIZE}px;
      margin: -${RIPPLE_SIZE / 2}px 0 0 -${RIPPLE_SIZE / 2}px;
      border: 3px solid ${RING};
      border-radius: 50%;
      pointer-events: none;
      z-index: 2147483647;
      animation: devscope-ripple 0.45s ease-out forwards;
    }
    @keyframes devscope-ripple {
      from { transform: scale(0.25); opacity: 1; }
      to   { transform: scale(1.15); opacity: 0; }
    }
  `;
  document.documentElement.appendChild(style);

  const halo = document.createElement('div');
  halo.id = HALO_ID;
  halo.style.transform = 'translate(-9999px, -9999px)';
  document.documentElement.appendChild(halo);

  const onMove = (e: PointerEvent): void => {
    halo.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
  };

  const onDown = (e: PointerEvent): void => {
    halo.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
    const ripple = document.createElement('div');
    ripple.className = 'devscope-recording-ripple';
    ripple.style.left = `${e.clientX}px`;
    ripple.style.top = `${e.clientY}px`;
    ripple.addEventListener('animationend', () => ripple.remove());
    document.documentElement.appendChild(ripple);
  };

  document.addEventListener('pointermove', onMove, { capture: true, passive: true });
  document.addEventListener('pointerdown', onDown, { capture: true, passive: true });

  w.__dsHaloCleanup = () => {
    document.removeEventListener('pointermove', onMove, { capture: true });
    document.removeEventListener('pointerdown', onDown, { capture: true });
    halo.remove();
    style.remove();
    document
      .querySelectorAll('.devscope-recording-ripple')
      .forEach((el) => el.remove());
    delete w.__dsHaloCleanup;
  };
}

/** Removes the halo overlay and its listeners; safe to call when not installed. */
export function recordingHaloCleanupInjected(): void {
  const w = window as unknown as { __dsHaloCleanup?: () => void };
  if (typeof w.__dsHaloCleanup === 'function') {
    try {
      w.__dsHaloCleanup();
    } catch {
      /* already gone */
    }
  }
}
