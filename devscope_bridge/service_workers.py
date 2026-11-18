"""Pick a Chrome service worker by extension id — never by list index 0.

Official Google Chrome preloads component extensions (Docs Offline, Hangouts
thunk.js, and others). `targets[0]` or `service_workers[0]` is often one of
those, not DevScope or the unpacked extension under test. Always match
`chrome-extension://<id>/`.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Default unpacked DevScope id on the Netcup QA host. Override at the call site
# when loading a different build.
DEFAULT_DEVSCOPE_EXTENSION_ID = "fkecddehojiphkojjppekhljacjcnnpo"

_SW_TYPES = {
    "service_worker",
    "service-worker",
    "serviceworker",
    "worker",
    "shared_worker",
    "shared-worker",
}


def _as_dict(item: Any) -> Mapping[str, Any]:
    if isinstance(item, Mapping):
        return item
    # Playwright Worker-like: .url
    url = getattr(item, "url", None)
    typ = getattr(item, "type", None) or "service_worker"
    return {"url": url or "", "type": typ}


def extension_id_from_url(url: str) -> str | None:
    """Return the 32-char Chrome extension id in a chrome-extension:// URL."""
    if not url:
        return None
    prefix = "chrome-extension://"
    lower = url.lower()
    if not lower.startswith(prefix):
        return None
    rest = url[len(prefix):]
    ext_id = rest.split("/", 1)[0].strip()
    return ext_id or None


def pick_service_worker(
    targets: Iterable[Any],
    extension_id: str,
) -> dict[str, Any] | None:
    """Return the service-worker target whose URL belongs to *extension_id*.

    Never returns ``targets[0]`` (or any other unfiltered first item) just
    because the list is non-empty. If several workers share the id, prefer one
    whose URL contains ``service-worker`` or ``offscreen``.
    """
    if not extension_id:
        raise ValueError("extension_id is required; refusing to guess a service worker")
    wanted = extension_id.lower()
    matches: list[dict[str, Any]] = []
    for raw in targets or []:
        item = dict(_as_dict(raw))
        url = str(item.get("url") or item.get("wsUrl") or "")
        typ = str(item.get("type") or item.get("targetType") or "").lower()
        found = extension_id_from_url(url)
        if not found or found.lower() != wanted:
            continue
        # Pages and offscreen documents can also match the id; prefer SW types
        # but still accept a SW-like URL even if type is missing.
        looks_sw = typ in _SW_TYPES or "service-worker" in url.lower() or "service_worker" in url.lower()
        item["_looks_sw"] = looks_sw
        matches.append(item)
    if not matches:
        return None
    sws = [m for m in matches if m.get("_looks_sw")]
    pool = sws or matches
    for needle in ("service-worker-loader", "service-worker", "offscreen"):
        for m in pool:
            if needle in str(m.get("url") or "").lower():
                return m
    return pool[0]
