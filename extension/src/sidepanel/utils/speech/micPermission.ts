const MIC_GRANT_PATH = 'mic-grant.html';

/** Open a full extension tab where Chrome will show the mic permission prompt. */
export async function openMicGrantPage(): Promise<void> {
  const url = chrome.runtime.getURL(MIC_GRANT_PATH);
  await chrome.tabs.create({ url, active: true });
}

/** Prime microphone permission — works in extension tabs/offscreen, not side panel. */
export async function ensureMicPermission(): Promise<boolean> {
  if (!navigator.mediaDevices?.getUserMedia) return true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    for (const track of stream.getTracks()) track.stop();
    return true;
  } catch {
    return false;
  }
}

export async function isMicGranted(): Promise<boolean> {
  try {
    const result = await chrome.storage.local.get('micGranted');
    return result.micGranted === true;
  } catch {
    return false;
  }
}
