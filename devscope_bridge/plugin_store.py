"""
plugin_store.py — the DevScope plugin store engine.

Catalog = a small curated FEATURED list + live search of the official MCP
Registry (registry.modelcontextprotocol.io — community-maintained, always
fresh). Install = additive edit of the workspace .cursor/mcp.json + `cursor-agent
mcp enable` (+ browser OAuth via `cursor-agent mcp login` when needed).

SAFETY: only REMOTE (url-based) servers are installable from the store — they
run on the provider's side. command-based servers execute local code and stay
a manual .cursor/mcp.json edit on purpose.

Once ready, plugins surface automatically as `plugin:<name>` capabilities
(capability_registry TTL scan) — usable by Claude via devscope_invoke and by
the autonomous employee. No extra wiring.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
from pathlib import Path

import httpx

from devscope_bridge import capability_registry
from devscope_bridge.session_manager_cursor import _resolve_cursor_bin
from devscope_bridge.session_store import DEFAULT_CWD

logger = logging.getLogger(__name__)

_REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers"
_SEARCH_TTL_S = 600.0
_SLUG_RE = re.compile(r"[^a-z0-9-]+")

_search_cache: dict[str, tuple[float, list[dict]]] = {}

FEATURED: list[dict] = [
    {"id": "notion", "title": "Notion", "url": "https://mcp.notion.com/mcp",
     "description": "Search, read, create and update pages, databases and tasks."},
    {"id": "linear", "title": "Linear", "url": "https://mcp.linear.app/mcp",
     "description": "Issues, projects and cycles in Linear."},
    {"id": "github", "title": "GitHub", "url": "https://api.githubcopilot.com/mcp/",
     "description": "Repos, issues, PRs and code search (GitHub official MCP)."},
    {"id": "sentry", "title": "Sentry", "url": "https://mcp.sentry.dev/mcp",
     "description": "Errors, issues and performance data from Sentry."},
    {"id": "atlassian", "title": "Atlassian (Jira/Confluence)",
     "url": "https://mcp.atlassian.com/v1/sse",
     "description": "Jira issues and Confluence pages."},
    {"id": "stripe", "title": "Stripe", "url": "https://mcp.stripe.com",
     "description": "Customers, payments and invoices (Stripe official MCP)."},
    {"id": "hugging-face", "title": "Hugging Face", "url": "https://huggingface.co/mcp",
     "description": "Models, datasets and Spaces on the Hub."},
    {"id": "deepwiki", "title": "DeepWiki", "url": "https://mcp.deepwiki.com/mcp",
     "description": "Ask questions about any public GitHub repository."},
]


def _slugify(name: str) -> str:
    tail = name.rsplit("/", 1)[-1].lower().replace("_", "-")
    return _SLUG_RE.sub("-", tail).strip("-")[:40] or "plugin"


def _pick_remote_url(remotes: list[dict]) -> str | None:
    for preferred in ("streamable-http", "sse"):
        for r in remotes:
            if r.get("type") == preferred and r.get("url"):
                return r["url"]
    return None


def _normalize_registry_entry(entry: dict) -> dict | None:
    server = entry.get("server") or {}
    meta = (entry.get("_meta") or {}).get("io.modelcontextprotocol.registry/official", {})
    if not meta.get("isLatest") or meta.get("status") != "active":
        return None
    url = _pick_remote_url(server.get("remotes") or [])
    if not url:
        return None  # command-based / no remote — not installable from the store
    return {
        "id": _slugify(server.get("name") or ""),
        "title": server.get("title") or _slugify(server.get("name") or ""),
        "description": (server.get("description") or "")[:200],
        "url": url,
        "source": "registry",
    }


async def search_catalog(query: str) -> list[dict]:
    """FEATURED (when no query) + live results from the official MCP registry."""
    q = (query or "").strip().lower()
    cached = _search_cache.get(q)
    if cached and time.monotonic() - cached[0] < _SEARCH_TTL_S:
        return cached[1]

    results: list[dict] = []
    if not q:
        results = [{**item, "source": "featured"} for item in FEATURED]
    else:
        results = [{**item, "source": "featured"} for item in FEATURED
                   if q in item["id"] or q in item["title"].lower()]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(_REGISTRY_URL, params={"search": q, "limit": 30})
                resp.raise_for_status()
                seen = {r["id"] for r in results}
                for entry in resp.json().get("servers", []):
                    item = _normalize_registry_entry(entry)
                    if item and item["id"] not in seen:
                        seen.add(item["id"])
                        results.append(item)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("MCP registry search failed: %s", exc)

    _search_cache[q] = (time.monotonic(), results)
    return results


# ── install / login / state (workspace .cursor/mcp.json + cursor-agent CLI) ──

def _cursor_mcp_path() -> Path:
    return Path(DEFAULT_CWD) / ".cursor" / "mcp.json"


def _read_cursor_config() -> dict:
    try:
        return json.loads(_cursor_mcp_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"mcpServers": {}}


def _run_cursor_cli(*args: str, timeout: int = 30) -> tuple[int, str]:
    binary = _resolve_cursor_bin()
    if not binary:
        return 127, "cursor-agent not found on PATH"
    try:
        out = subprocess.run([binary, *args], capture_output=True, text=True,
                             timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return out.returncode, (out.stdout or "") + (out.stderr or "")


def _invalidate_status_caches() -> None:
    capability_registry._mcp_status_cache = None


async def install(plugin_id: str, title: str, url: str) -> dict:
    """Register a REMOTE MCP in .cursor/mcp.json, enable it, report its state."""
    slug = _slugify(plugin_id)
    if not url.startswith("https://"):
        return {"ok": False, "error": "only https:// remote MCP servers are installable"}

    config = _read_cursor_config()
    servers = config.setdefault("mcpServers", {})
    existing = servers.get(slug)
    if existing and existing.get("url") != url:
        return {"ok": False, "error": f"'{slug}' already configured with a different URL"}
    if not existing:
        servers[slug] = {"url": url,
                         "description": f"{title} (installed from the DevScope plugin store)"}
        path = _cursor_mcp_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    code, output = await asyncio.to_thread(_run_cursor_cli, "mcp", "enable", slug)
    if code != 0:
        return {"ok": False, "error": f"enable failed: {output.strip()[:300]}"}
    _invalidate_status_caches()
    status = (await capability_registry.cursor_mcp_status()).get(slug, "unknown")
    return {"ok": True, "id": slug, "status": status,
            "needs_login": "auth" in status.lower()}


async def start_login(plugin_id: str) -> dict:
    """Spawn `cursor-agent mcp login <slug>` detached — it opens the user's browser."""
    slug = _slugify(plugin_id)
    binary = _resolve_cursor_bin()
    if not binary:
        return {"ok": False, "error": "cursor-agent not found on PATH"}
    try:
        subprocess.Popen([binary, "mcp", "login", slug], cwd=DEFAULT_CWD,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    _invalidate_status_caches()
    return {"ok": True, "started": True,
            "note": "Approve the OAuth request in the browser, then refresh."}


async def state() -> dict:
    """Installed plugins (from .cursor/mcp.json) merged with live CLI status."""
    _invalidate_status_caches()
    status = await capability_registry.cursor_mcp_status()
    servers = _read_cursor_config().get("mcpServers", {})
    items = []
    for slug, entry in servers.items():
        raw = status.get(slug, "not loaded")
        items.append({
            "id": slug,
            "url": entry.get("url"),
            "description": entry.get("description") or "",
            "status": raw,
            "ready": raw.lower().startswith("ready"),
            "needs_login": "auth" in raw.lower(),
        })
    return {"plugins": items}
