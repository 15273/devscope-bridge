"""Tests for WebM → MP4 transcode helper."""

from unittest.mock import MagicMock, patch

import pytest

from devscope_bridge.recording_transcode import find_ffmpeg, webm_to_mp4


def test_find_ffmpeg_returns_path_when_present():
    with patch("devscope_bridge.recording_transcode.shutil.which", return_value="/usr/bin/ffmpeg"):
        assert find_ffmpeg() == "/usr/bin/ffmpeg"


def test_webm_to_mp4_requires_ffmpeg():
    with patch("devscope_bridge.recording_transcode.find_ffmpeg", return_value=None):
        with pytest.raises(RuntimeError, match="ffmpeg not found"):
            webm_to_mp4(b"fake-webm")


def test_webm_to_mp4_success():
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42"

    def fake_run(cmd, capture_output, timeout):
        out_path = cmd[-1]
        with open(out_path, "wb") as f:
            f.write(fake_mp4)
        return MagicMock(returncode=0, stderr=b"")

    with patch("devscope_bridge.recording_transcode.find_ffmpeg", return_value="/usr/bin/ffmpeg"):
        with patch("devscope_bridge.recording_transcode.subprocess.run", side_effect=fake_run):
            assert webm_to_mp4(b"webm-bytes") == fake_mp4
