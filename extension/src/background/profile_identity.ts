/**
 * profile_identity.ts — stable per-Chrome-profile identity.
 *
 * chrome.storage.local is scoped to the Chrome profile, so a UUID stored there
 * uniquely (and stably) identifies the profile the extension is running in.
 * The bridge uses this id to list tabs across all connected profiles and to
 * route actions to the profile that owns a given tab.
 *
 * Only the service worker context calls this (it has chrome.storage + identity);
 * the resolved identity is pushed down to the offscreen document.
 */

const PROFILE_ID_KEY = 'devscopeProfileId';
const PROFILE_LABEL_KEY = 'devscopeProfileLabel';

export interface ProfileIdentity {
  profileId: string;
  profileLabel: string;
}

function randomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `p_${Math.abs(Date.now()).toString(36)}_${Math.floor(Math.random() * 1e9).toString(36)}`;
}

/** Best-effort human label for the profile (account email if granted, else short id). */
async function resolveLabel(profileId: string): Promise<string> {
  try {
    const stored = await chrome.storage.local.get(PROFILE_LABEL_KEY);
    const existing = stored[PROFILE_LABEL_KEY] as string | undefined;
    if (existing) return existing;
  } catch {
    /* fall through */
  }
  let label = `Profile ${profileId.slice(0, 6)}`;
  try {
    const identity = (chrome as unknown as { identity?: { getProfileUserInfo?: () => Promise<{ email?: string }> } }).identity;
    const info = await identity?.getProfileUserInfo?.();
    if (info?.email) label = info.email;
  } catch {
    /* identity permission not granted — keep the short-id label */
  }
  try {
    await chrome.storage.local.set({ [PROFILE_LABEL_KEY]: label });
  } catch {
    /* non-fatal */
  }
  return label;
}

export async function getProfileIdentity(): Promise<ProfileIdentity> {
  let profileId = '';
  try {
    const stored = await chrome.storage.local.get(PROFILE_ID_KEY);
    profileId = (stored[PROFILE_ID_KEY] as string | undefined) ?? '';
  } catch {
    /* storage unavailable — generate ephemeral id */
  }
  if (!profileId) {
    profileId = randomId();
    try {
      await chrome.storage.local.set({ [PROFILE_ID_KEY]: profileId });
    } catch {
      /* non-fatal */
    }
  }
  const profileLabel = await resolveLabel(profileId);
  return { profileId, profileLabel };
}
