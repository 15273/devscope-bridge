/**
 * useRecording — start/stop tab video recording and track live state.
 *
 * tabCapture runs in the service worker (tabCapture permission — no user gesture).
 * The worker resolves the host-window tab via resolveRecordTab(), same as screenshots.
 *
 * Flow: start_recording → SW getMediaStreamId → offscreen recorder_start
 * Stop: recorder_stop → offscreen exports MP4 (native or ffmpeg via bridge)
 */
import { useCallback, useEffect, useState } from 'react';
import type { RecordingStatusMsg } from '@/shared/messaging';

export function useRecording(): {
  recording: boolean;
  recordingPending: boolean;
  startedAt: number | null;
  error: string;
  toggle: () => void;
} {
  const [recording, setRecording] = useState(false);
  const [recordingPending, setRecordingPending] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    function onMessage(msg: unknown) {
      const m = msg as RecordingStatusMsg;
      if (m?.kind !== 'recording_status') return;
      setRecording(m.recording);
      setRecordingPending(false);
      setStartedAt(m.recording ? Date.now() : null);
      if (m.error) {
        setError(m.error);
        setTimeout(() => setError(''), 8000);
      }
    }
    chrome.runtime.onMessage.addListener(onMessage);
    return () => chrome.runtime.onMessage.removeListener(onMessage);
  }, []);

  const toggle = useCallback(() => {
    setError('');

    if (recording || recordingPending) {
      setRecordingPending(false);
      chrome.runtime.sendMessage({ kind: 'recorder_stop' }).catch(() => {
        setError("Couldn't stop recording.");
      });
      return;
    }

    setRecordingPending(true);

    void chrome.runtime
      .sendMessage({ kind: 'start_recording' })
      .then((resp: { ok?: boolean; error?: string } | undefined) => {
        if (resp?.ok === false && resp.error) {
          setRecordingPending(false);
          setError(resp.error);
          setTimeout(() => setError(''), 8000);
          return;
        }
        // Fallback if offscreen never acks (e.g. doc not listening).
        window.setTimeout(() => {
          setRecordingPending((pending) => {
            if (pending) {
              setError('Recording did not start — reload the extension and try again.');
            }
            return false;
          });
        }, 8_000);
      })
      .catch(() => {
        setRecordingPending(false);
        setError('Could not reach the extension background — reload and try again.');
        setTimeout(() => setError(''), 8000);
      });
  }, [recording, recordingPending]);

  return { recording, recordingPending, startedAt, error, toggle };
}
