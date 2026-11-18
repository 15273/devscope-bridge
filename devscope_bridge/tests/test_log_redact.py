"""Bearer tokens must never appear in formatted log records or helper output."""

import logging

from devscope_bridge.log_redact import (
    RedactingFilter,
    redact_secrets,
    redact_url_query,
    set_known_token,
)


def test_redacts_bearer_and_reports_length():
    text = "Authorization: Bearer super-secret-token-value"
    out = redact_secrets(text)
    assert "super-secret-token-value" not in out
    assert "redacted token len=24" in out


def test_redacts_query_token():
    text = "GET /sessions?token=abcd1234efgh HTTP/1.1"
    out = redact_secrets(text)
    assert "abcd1234efgh" not in out
    assert "token=[redacted token len=12]" in out


def test_redacts_known_token_without_prefix():
    set_known_token("plain-token-xyz")
    try:
        out = redact_secrets("boot with plain-token-xyz in this line")
        assert "plain-token-xyz" not in out
        assert "redacted token len=15" in out
    finally:
        set_known_token(None)


def test_redact_url_query_strips_search_and_hash():
    assert redact_url_query("https://example.com/x?token=sekrit#frag") == "https://example.com/x"


def test_logging_filter_redacts_args(caplog):
    set_known_token("sekrit-token")
    logger = logging.getLogger("devscope_bridge.tests.redact")
    logger.setLevel(logging.INFO)
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger=logger.name):
        logger.info("header Bearer %s", "sekrit-token")
    try:
        assert "sekrit-token" not in caplog.text
        assert "redacted token" in caplog.text
    finally:
        set_known_token(None)
        caplog.clear()
