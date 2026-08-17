/**
 * helpers.ts — shared primitives for the session store reducers.
 * (Type-only imports from sessionStore — no runtime cycle.)
 */
import type { SessionState, StoreState } from './sessionStore';

export function nextId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function updateSession(
  state: StoreState,
  name: string,
  updater: (s: SessionState) => SessionState,
): StoreState {
  const existing = state.sessions[name];
  if (!existing) return state;
  return {
    ...state,
    sessions: { ...state.sessions, [name]: updater(existing) },
  };
}
