"""Never pick targets[0] when it is a component service worker."""

import pytest

from devscope_bridge.service_workers import (
    DEFAULT_DEVSCOPE_EXTENSION_ID,
    extension_id_from_url,
    pick_service_worker,
)

HANGOUTS = "nkeimhogjdpnpccoofpliimaahmaaome"
DEVSCOPE = DEFAULT_DEVSCOPE_EXTENSION_ID


def test_extension_id_from_url():
    assert extension_id_from_url(
        f"chrome-extension://{DEVSCOPE}/service-worker-loader.js"
    ) == DEVSCOPE
    assert extension_id_from_url("https://example.com/") is None


def test_refuses_empty_extension_id():
    with pytest.raises(ValueError, match="extension_id is required"):
        pick_service_worker([{"url": "chrome-extension://abc/sw.js", "type": "service_worker"}], "")


def test_never_returns_component_sw_at_index_zero():
    targets = [
        {"url": f"chrome-extension://{HANGOUTS}/thunk.js", "type": "service_worker"},
        {"url": "https://mail.google.com/", "type": "page"},
        {"url": f"chrome-extension://{DEVSCOPE}/service-worker-loader.js", "type": "service_worker"},
    ]
    picked = pick_service_worker(targets, DEVSCOPE)
    assert picked is not None
    assert DEVSCOPE in picked["url"]
    assert HANGOUTS not in picked["url"]


def test_returns_none_when_id_is_absent():
    targets = [
        {"url": f"chrome-extension://{HANGOUTS}/thunk.js", "type": "service_worker"},
        {"url": "https://example.com", "type": "page"},
    ]
    assert pick_service_worker(targets, DEVSCOPE) is None


def test_prefers_service_worker_loader_when_several_match():
    targets = [
        {"url": f"chrome-extension://{DEVSCOPE}/offscreen.html", "type": "page"},
        {"url": f"chrome-extension://{DEVSCOPE}/service-worker-loader.js", "type": "service_worker"},
    ]
    picked = pick_service_worker(targets, DEVSCOPE)
    assert "service-worker-loader" in picked["url"]


def test_accepts_objects_with_url_attribute():
    class Worker:
        def __init__(self, url):
            self.url = url
            self.type = "service_worker"

    workers = [
        Worker(f"chrome-extension://{HANGOUTS}/thunk.js"),
        Worker(f"chrome-extension://{DEVSCOPE}/background.js"),
    ]
    picked = pick_service_worker(workers, DEVSCOPE)
    assert picked["url"].endswith("background.js")
