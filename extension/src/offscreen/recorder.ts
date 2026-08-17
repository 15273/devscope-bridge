/**
 * recorder.ts — Tab-capture MediaRecorder that lives inside the offscreen document.
 *
 * Exports MP4: native MediaRecorder when Chrome supports it, otherwise WebM →
 * bridge /recordings/to-mp4 (local ffmpeg).
 */

import type { RecordingStatusMsg } from '@/shared/messaging';
import { transcodeWebmToMp4 } from './recordingExport';

let mediaRecorder: MediaRecorder | null = null;
let stream: MediaStream | null = null;
let audioPassthrough: AudioContext | null = null;
let chunks: Blob[] = [];
let bridgeToken = '';

function log(...args: unknown[]): void {
  console.log('[DevScope recorder]', ...args);
}

function broadcastStatus(recording: boolean, error?: string): void {
  const msg: RecordingStatusMsg = { kind: 'recording_status', recording, ...(error ? { error } : {}) };
  chrome.runtime.sendMessage(msg).catch(() => {});
}

function pickMimeType(hasAudio: boolean): string {
  const withAudio = [
    'video/mp4;codecs=avc1,mp4a.40.2',
    'video/mp4;codecs=h264,aac',
    'video/webm;codecs=vp9,opus',
    'video/webm;codecs=vp8,opus',
  ];
  const videoOnly = [
    'video/mp4;codecs=avc1',
    'video/mp4;codecs=h264',
    'video/mp4',
    'video/webm;codecs=vp9',
    'video/webm;codecs=vp8',
    'video/webm',
  ];
  const candidates = hasAudio ? [...withAudio, ...videoOnly] : videoOnly;
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return '';
}

function isMp4Mime(mime: string): boolean {
  return mime.toLowerCase().includes('mp4');
}

function buildFilename(mime: string): string {
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const ext = isMp4Mime(mime) ? 'mp4' : 'webm';
  return `devscope-recording-${ts}.${ext}`;
}

function downloadBlob(blob: Blob, mime: string): void {
  const url = URL.createObjectURL(blob);
  const filename = buildFilename(mime);

  if (chrome.downloads?.download) {
    chrome.downloads.download({ url, filename, saveAs: false }, (downloadId) => {
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      if (downloadId === undefined) {
        log('chrome.downloads failed, falling back to anchor click');
        anchorDownload(url, filename);
      } else {
        log('download started, id:', downloadId, filename);
      }
    });
  } else {
    anchorDownload(url, filename);
  }
}

function anchorDownload(url: string, filename: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function cleanupStream(): void {
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
  audioPassthrough?.close().catch(() => {});
  audioPassthrough = null;
}

/**
 * Capturing tab audio mutes the tab for the user — route the captured audio
 * back to the speakers so the page stays audible while recording.
 */
function keepTabAudible(captured: MediaStream): void {
  if (captured.getAudioTracks().length === 0) return;
  audioPassthrough = new AudioContext();
  audioPassthrough
    .createMediaStreamSource(captured)
    .connect(audioPassthrough.destination);
}

function tabCaptureConstraints(streamId: string, withAudio: boolean): MediaStreamConstraints {
  const mandatory = {
    chromeMediaSource: 'tab',
    chromeMediaSourceId: streamId,
  };
  return {
    // @ts-expect-error — mandatory is a Chrome-specific tabCapture constraint
    video: { mandatory },
    // @ts-expect-error — mandatory is a Chrome-specific tabCapture constraint
    audio: withAudio ? { mandatory } : false,
  };
}

async function deliverRecording(blob: Blob, mime: string): Promise<void> {
  if (isMp4Mime(mime)) {
    downloadBlob(blob, mime);
    return;
  }

  try {
    log('transcoding WebM → MP4 via bridge…');
    const mp4 = await transcodeWebmToMp4(blob, bridgeToken);
    downloadBlob(mp4, 'video/mp4');
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    log('MP4 export failed, falling back to WebM:', message);
    downloadBlob(blob, mime);
    broadcastStatus(
      false,
      `MP4 export failed (${message}) — saved WebM instead. Install ffmpeg: brew install ffmpeg`,
    );
  }
}

export async function startRecording(streamId: string, token = ''): Promise<void> {
  bridgeToken = token;

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    log('already recording — ignoring start');
    broadcastStatus(true);
    return;
  }

  log('startRecording with streamId:', streamId.slice(0, 8) + '…');

  let capturedStream: MediaStream;
  try {
    capturedStream = await navigator.mediaDevices.getUserMedia(
      tabCaptureConstraints(streamId, true),
    );
  } catch (audioErr) {
    log('tab capture with audio failed, retrying video-only:', String(audioErr));
    try {
      capturedStream = await navigator.mediaDevices.getUserMedia(
        tabCaptureConstraints(streamId, false),
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      log('getUserMedia failed:', message);
      broadcastStatus(false, `Could not capture tab: ${message}`);
      return;
    }
  }

  stream = capturedStream;
  chunks = [];
  keepTabAudible(capturedStream);

  const hasAudio = capturedStream.getAudioTracks().length > 0;
  log('captured tracks — video:', capturedStream.getVideoTracks().length, 'audio:', hasAudio);

  const mimeType = pickMimeType(hasAudio);
  const recorderOptions = mimeType ? { mimeType } : {};
  mediaRecorder = new MediaRecorder(capturedStream, recorderOptions);
  log('MediaRecorder created, mimeType:', mediaRecorder.mimeType);

  mediaRecorder.ondataavailable = (e: BlobEvent) => {
    if (e.data.size > 0) chunks.push(e.data);
  };

  mediaRecorder.onstop = () => {
    log('MediaRecorder stopped — assembling blob from', chunks.length, 'chunks');
    const mime = mediaRecorder?.mimeType ?? 'video/webm';
    const blob = new Blob(chunks, { type: mime });
    chunks = [];
    cleanupStream();
    mediaRecorder = null;
    broadcastStatus(false);
    if (blob.size > 0) {
      void deliverRecording(blob, mime);
    } else {
      log('recording blob was empty — nothing to download');
    }
  };

  mediaRecorder.onerror = (e: Event) => {
    const detail = (e as ErrorEvent).message ?? 'MediaRecorder error';
    log('MediaRecorder error:', detail);
    cleanupStream();
    mediaRecorder = null;
    chunks = [];
    broadcastStatus(false, detail);
  };

  capturedStream.getVideoTracks().forEach((track) => {
    track.onended = () => {
      log('video track ended externally — stopping recorder');
      stopRecording();
    };
  });

  mediaRecorder.start(1_000);
  broadcastStatus(true);
  log('recording started');
}

export function stopRecording(): void {
  if (!mediaRecorder || mediaRecorder.state === 'inactive') {
    log('stopRecording called but nothing is recording');
    return;
  }
  log('stopping recorder');
  mediaRecorder.stop();
}
