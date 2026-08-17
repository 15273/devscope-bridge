"""
test_logging_config.py — A10/RC-12: timestamped, rotating logs + quiet
uvicorn access noise.

Bare logging.basicConfig had no timestamps, no rotation (bridge log files had
grown to 312MB+3.2GB), and uvicorn's access logger stayed at INFO — every
poll-heavy endpoint (GET /sessions, /transcript) logged a line.
"""

import logging
from logging.handlers import RotatingFileHandler

import pytest

import devscope_bridge.main as bridge_main


@pytest.fixture
def clean_root_logger():
    """Remove any handlers this test adds so they don't leak into other tests."""
    root = logging.getLogger()
    before = list(root.handlers)
    yield root
    for h in list(root.handlers):
        if h not in before:
            root.removeHandler(h)
            h.close()


def test_configure_logging_adds_rotating_file_handler(tmp_path, clean_root_logger):
    bridge_main._configure_logging(log_dir=tmp_path)

    file_handlers = [
        h for h in clean_root_logger.handlers if isinstance(h, RotatingFileHandler)
    ]
    assert len(file_handlers) >= 1, "Expected a RotatingFileHandler on the root logger"
    handler = file_handlers[-1]
    assert handler.maxBytes == bridge_main._LOG_MAX_BYTES
    assert handler.backupCount == bridge_main._LOG_BACKUP_COUNT
    assert (tmp_path / "bridge.log").exists()


def test_configure_logging_uses_timestamped_format(tmp_path, clean_root_logger):
    bridge_main._configure_logging(log_dir=tmp_path)

    file_handlers = [
        h for h in clean_root_logger.handlers if isinstance(h, RotatingFileHandler)
    ]
    fmt = file_handlers[-1].formatter._fmt
    assert "%(asctime)s" in fmt


def test_configure_logging_quiets_uvicorn_access(tmp_path, clean_root_logger):
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    bridge_main._configure_logging(log_dir=tmp_path)
    assert logging.getLogger("uvicorn.access").level == logging.WARNING
