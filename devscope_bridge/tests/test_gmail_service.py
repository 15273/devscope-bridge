# test_gmail_service.py — pure parse functions tested without network.
from devscope_bridge.gmail import gmail_service


def test_parse_thread_extracts_headers_and_snippet():
    raw = {
        "id": "t1",
        "messages": [{
            "snippet": "Hello there",
            "payload": {"headers": [
                {"name": "From", "value": "Dana <dana@x.com>"},
                {"name": "Subject", "value": "Interview"},
                {"name": "Date", "value": "Mon, 14 Jun 2026 10:00:00 +0300"},
            ]},
        }],
    }
    out = gmail_service.parse_thread(raw)
    assert out["id"] == "t1"
    assert out["subject"] == "Interview"
    assert out["messages"][0]["from"] == "Dana <dana@x.com>"
    assert out["messages"][0]["snippet"] == "Hello there"


def test_parse_thread_header_case_insensitive():
    raw = {
        "id": "t2",
        "messages": [{
            "snippet": "Hi",
            "payload": {"headers": [
                {"name": "from", "value": "alice@x.com"},
                {"name": "SUBJECT", "value": "Hello"},
                {"name": "date", "value": "Tue, 15 Jun 2026 09:00:00 +0300"},
            ]},
        }],
    }
    out = gmail_service.parse_thread(raw)
    assert out["subject"] == "Hello"
    assert out["messages"][0]["from"] == "alice@x.com"


def test_parse_thread_empty_messages():
    raw = {"id": "t3", "messages": []}
    out = gmail_service.parse_thread(raw)
    assert out["id"] == "t3"
    assert out["subject"] == ""
    assert out["messages"] == []


def test_header_returns_empty_string_when_missing():
    headers = [{"name": "From", "value": "x@y.com"}]
    assert gmail_service._header(headers, "Subject") == ""
    assert gmail_service._header(headers, "From") == "x@y.com"
