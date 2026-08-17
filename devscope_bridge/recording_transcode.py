"""Convert DevScope tab recordings (WebM) to MP4 via local ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

_MAX_BYTES = 200 * 1024 * 1024
_DEFAULT_TIMEOUT_S = 120.0


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def webm_to_mp4(webm_bytes: bytes, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> bytes:
    """Transcode WebM bytes to MP4 (H.264 + AAC audio). Raises RuntimeError on failure."""
    if not webm_bytes:
        raise RuntimeError("empty recording")
    if len(webm_bytes) > _MAX_BYTES:
        raise RuntimeError("recording too large for transcode")

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found — install with: brew install ffmpeg")

    with tempfile.TemporaryDirectory(prefix="devscope-rec-") as tmp:
        inp = Path(tmp) / "input.webm"
        out = Path(tmp) / "output.mp4"
        inp.write_bytes(webm_bytes)
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(inp),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-movflags",
                "+faststart",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                str(out),
            ],
            capture_output=True,
            timeout=timeout_s,
        )
        if proc.returncode != 0:
            tail = proc.stderr.decode(errors="replace")[-480:]
            raise RuntimeError(f"ffmpeg failed: {tail.strip() or proc.returncode}")
        mp4 = out.read_bytes()
        if not mp4:
            raise RuntimeError("ffmpeg produced empty mp4")
        return mp4
