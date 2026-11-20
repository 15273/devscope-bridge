"""List and teleport Claude Code cloud sessions (claude.ai/code).

Listing uses the same GET /v1/code/sessions the CLI teleport picker uses.
Import runs `claude --teleport <id>` in a matching local checkout, then the
session is a normal local `--resume` conversation.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from devscope_bridge.claude_session_index import (
    SOURCE_CLAUDE_CLOUD,
    DiscoveredSession,
    _clip,
    _TITLE_MAX,
)

logger = logging.getLogger(__name__)

CLOUD_SESSIONS_URL = "https://api.anthropic.com/v1/code/sessions"
_OWNER_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_GIT_TIMEOUT_S = 8
_TELEPORT_TIMEOUT_S = 180


class CloudTeleportError(Exception):
    """User-facing failure preparing or running a cloud teleport."""


class CloudAuthError(Exception):
    """Missing or rejected claude.ai OAuth token."""


class CloudNotFoundError(Exception):
    """Cloud session id does not exist for this account."""


class CloudAlreadyImported(Exception):
    def __init__(self, bridge_name: str):
        super().__init__(f"Already imported as {bridge_name}")
        self.bridge_name = bridge_name


def parse_cloud_session_ref(value: str) -> str | None:
    """Accept a bare cloud session id or a claude.ai/code URL."""
    raw = (value or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"(?:session|cse)_[A-Za-z0-9_-]+", raw, re.IGNORECASE):
        return raw
    path = raw
    if "://" not in path and path.startswith("claude.ai/"):
        path = "https://" + path
    try:
        parsed = urlparse(path)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host and host != "claude.ai":
        return None
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) >= 2 and parts[0] == "code":
        candidate = parts[1]
        if re.fullmatch(r"(?:session|cse)_[A-Za-z0-9_-]+", candidate, re.IGNORECASE):
            return candidate
    return None


def parse_git_owner_name(url: str) -> str | None:
    """Return lowercase owner/name from a git remote URL or owner/name pair."""
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw and "@" not in raw and raw.count("/") == 1:
        owner, name = raw.split("/", 1)
        name = name.removesuffix(".git")
        if _ok_git_part(owner) and _ok_git_part(name):
            return f"{owner}/{name}".lower()
    host_path = raw
    if raw.startswith("git@") and ":" in raw:
        host_path = raw.split(":", 1)[1]
    elif "://" in raw:
        parsed = urlparse(raw)
        host_path = parsed.path or ""
    host_path = host_path.lstrip("/")
    if host_path.endswith(".git"):
        host_path = host_path[: -len(".git")]
    parts = [p for p in host_path.split("/") if p]
    if len(parts) < 2:
        logger.debug("Could not parse repository from: %s", url)
        return None
    owner, name = parts[-2], parts[-1]
    if not _ok_git_part(owner) or not _ok_git_part(name):
        return None
    return f"{owner}/{name}".lower()


def _ok_git_part(value: str) -> bool:
    return bool(_OWNER_NAME_RE.match(value)) and not value.startswith("-") and value not in (".", "..")


def _git_source(raw: dict) -> dict | None:
    sources = (raw.get("config") or {}).get("sources") or []
    if not isinstance(sources, list):
        return None
    for src in sources:
        if isinstance(src, dict) and src.get("type") == "git_repository":
            return src
    return None


def parse_cloud_session_list(
    payload: dict | list,
    *,
    checkout_lookup: Callable[[str], str | None] | None = None,
    owner_lookup: Callable[[str], str | None] | None = None,
) -> list[DiscoveredSession]:
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    items: list[DiscoveredSession] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") == "archived":
            continue
        session_id = str(row.get("id") or "").strip()
        if not session_id or parse_cloud_session_ref(session_id) is None:
            continue
        source = _git_source(row)
        repo = parse_git_owner_name(str((source or {}).get("url") or ""))
        checkout = checkout_lookup(repo) if repo and checkout_lookup else None
        title = str(row.get("title") or "").strip() or "Untitled"
        last_used = str(row.get("last_event_at") or row.get("created_at") or "")
        owner = owner_lookup(session_id) if owner_lookup else None
        items.append(
            DiscoveredSession(
                session_id=session_id,
                title=_clip(title, _TITLE_MAX),
                cwd=checkout or repo or "",
                source=SOURCE_CLAUDE_CLOUD,
                last_used=last_used,
                can_resume=bool(checkout and os.path.isdir(checkout)),
                already_imported=bool(owner),
                bridge_name=owner,
            )
        )
    return items


def working_tree_dirty(cwd: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return True
    if proc.returncode != 0:
        return True
    return bool(proc.stdout.strip())


def _remote_urls(cwd: str) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "remote", "-v"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    urls: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            urls.append(parts[1])
    return urls


def resolve_local_checkout(repo: str, candidate_cwds: list[str]) -> str | None:
    want = (repo or "").lower()
    if not want:
        return None
    seen: set[str] = set()
    for cwd in candidate_cwds:
        if not cwd or cwd in seen:
            continue
        seen.add(cwd)
        if not os.path.isdir(cwd):
            continue
        for url in _remote_urls(cwd):
            if parse_git_owner_name(url) == want:
                return cwd
    return None


def candidate_cwds_from_disk() -> list[str]:
    from devscope_bridge import claude_session_index as index
    from devscope_bridge import session_store

    cwds: list[str] = []
    for entry in session_store.load_sessions().values():
        cwd = entry.get("cwd")
        if cwd:
            cwds.append(str(cwd))
    for item in index.discover_sessions():
        if item.cwd:
            cwds.append(item.cwd)
    return cwds


def prepare_cloud_teleport(
    session: dict,
    *,
    candidate_cwds: list[str] | None = None,
) -> tuple[str, str]:
    """Validate repo + clean git. Returns (cwd, session_id). Does not mutate git."""
    session_id = str(session.get("id") or "").strip()
    if parse_cloud_session_ref(session_id) is None:
        raise CloudTeleportError("Not a cloud session id")
    source = _git_source(session)
    repo = parse_git_owner_name(str((source or {}).get("url") or ""))
    if not repo:
        raise CloudTeleportError("Cloud session has no GitHub repository")
    cwd = resolve_local_checkout(repo, candidate_cwds or candidate_cwds_from_disk())
    if not cwd:
        raise CloudTeleportError(
            f"No local checkout of {repo}. Clone it first, then import again."
        )
    if working_tree_dirty(cwd):
        raise CloudTeleportError(
            f"uncommitted changes in {cwd}. Commit, stash, or discard them, then import."
        )
    return cwd, session_id


def _init_session_id(line: str) -> str | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    sid = str(event.get("session_id") or "").strip()
    if not sid:
        return None
    if event.get("type") == "system" or event.get("subtype") == "init":
        return sid
    if event.get("type") == "result" and sid:
        return sid
    return None


def run_teleport(session_id: str, cwd: str) -> str:
    """Pull a cloud session into cwd. Returns the local session id for --resume.

    Keeps stdin open until init arrives so teleport can finish git fetch/checkout
    without treating an immediate EOF as a missing prompt.
    """
    cmd = [
        "claude",
        "--teleport",
        session_id,
        "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
    ]
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["CI"] = "1"
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )
    except FileNotFoundError as exc:
        raise CloudTeleportError("claude CLI not found on PATH") from exc

    found: queue.Queue[str | None] = queue.Queue()
    stderr_chunks: list[str] = []

    def read_stdout() -> None:
        try:
            if proc.stdout is None:
                found.put(None)
                return
            for line in proc.stdout:
                sid = _init_session_id(line)
                if sid:
                    found.put(sid)
                    return
            found.put(None)
        except Exception:
            found.put(None)

    def read_stderr() -> None:
        try:
            if proc.stderr is not None:
                stderr_chunks.append(proc.stderr.read() or "")
        except Exception:
            pass

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()
    local_id = ""
    try:
        try:
            got = found.get(timeout=_TELEPORT_TIMEOUT_S)
        except queue.Empty:
            raise CloudTeleportError(
                f"claude --teleport timed out in {cwd}."
            ) from None
        local_id = got or ""
    finally:
        if proc.poll() is None:
            if proc.stdin:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    if not local_id:
        local_id = _find_transcript_id(cwd, session_id) or ""
    if not local_id:
        detail = "".join(stderr_chunks).strip()[-2000:] or f"exit {proc.returncode}"
        raise CloudTeleportError(f"Teleport failed: {detail}")
    return local_id


def _find_transcript_id(cwd: str, cloud_id: str) -> str | None:
    projects = Path.home() / ".claude" / "projects"
    if not projects.is_dir():
        return None
    direct = list(projects.glob(f"*/{cloud_id}.jsonl"))
    if direct:
        return cloud_id
    encoded = "".join(ch if ch.isalnum() else "-" for ch in cwd)
    folder = projects / encoded
    if folder.is_dir():
        jsonls = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if jsonls:
            return jsonls[0].stem
    return None


def list_payload_from_api(payload: dict | list, *, candidate_cwds: list[str] | None = None) -> list[DiscoveredSession]:
    from devscope_bridge import session_store

    cwds = candidate_cwds if candidate_cwds is not None else candidate_cwds_from_disk()

    def checkout_lookup(repo: str) -> str | None:
        return resolve_local_checkout(repo, cwds)

    return parse_cloud_session_list(
        payload,
        checkout_lookup=checkout_lookup,
        owner_lookup=session_store.session_ref_owner,
    )


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }


def _unwrap_session(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("response_shape", "session", "data"):
        inner = payload.get(key)
        if isinstance(inner, dict) and inner.get("id"):
            return inner
    return payload


async def _get_json(url: str, token: str) -> tuple[int, object]:
    import httpx

    async with httpx.AsyncClient(timeout=6.0) as client:
        resp = await client.get(url, headers=_auth_headers(token))
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body


async def fetch_cloud_sessions(
    *,
    candidate_cwds: list[str] | None = None,
) -> tuple[list[DiscoveredSession], str | None]:
    from devscope_bridge.oauth_usage_service import read_oauth_token

    token = await read_oauth_token()
    if not token:
        return [], "Sign in with claude.ai (`claude auth login`) to list cloud sessions."
    try:
        status, payload = await _get_json(f"{CLOUD_SESSIONS_URL}?limit=100", token)
    except Exception as exc:
        logger.info("cloud session list failed: %s", exc)
        return [], f"Could not list cloud sessions: {exc}"
    if status in (401, 403):
        return [], "Sign in with claude.ai (`claude auth login`) to list cloud sessions."
    if status != 200:
        return [], f"Could not list cloud sessions (HTTP {status})."
    if not isinstance(payload, (dict, list)):
        return [], "Could not list cloud sessions."
    return list_payload_from_api(payload, candidate_cwds=candidate_cwds), None


async def fetch_cloud_session(session_id: str) -> dict:
    from devscope_bridge.oauth_usage_service import read_oauth_token

    token = await read_oauth_token()
    if not token:
        raise CloudAuthError(
            "Sign in with claude.ai (`claude auth login`) to import cloud sessions."
        )
    try:
        status, payload = await _get_json(
            f"{CLOUD_SESSIONS_URL}/{session_id}", token
        )
    except Exception as exc:
        raise CloudTeleportError(f"Could not fetch cloud session: {exc}") from exc
    if status in (401, 403):
        raise CloudAuthError(
            "Sign in with claude.ai (`claude auth login`) to import cloud sessions."
        )
    if status == 404:
        raise CloudNotFoundError("Claude cloud session not found")
    if status != 200:
        raise CloudTeleportError(f"Could not fetch cloud session (HTTP {status})")
    raw = _unwrap_session(payload)
    if not raw.get("id"):
        raw = {**raw, "id": session_id}
    return raw


async def import_cloud_session(session_ref: str) -> dict:
    from devscope_bridge import session_store
    from devscope_bridge.claude_session_index import SOURCE_CLAUDE_CLOUD

    sid = parse_cloud_session_ref(session_ref)
    if not sid:
        raise CloudTeleportError("Not a cloud session id or claude.ai/code URL")
    owner = session_store.session_ref_owner(sid)
    if owner:
        raise CloudAlreadyImported(owner)
    raw = await fetch_cloud_session(sid)
    if not raw.get("id"):
        raw["id"] = sid
    cwd, cloud_id = prepare_cloud_teleport(raw)
    local_id = run_teleport(cloud_id, cwd)
    title = str(raw.get("title") or "").strip() or cloud_id
    return session_store.import_claude_session(
        session_id=local_id,
        source=SOURCE_CLAUDE_CLOUD,
        cwd=cwd,
        display_title=title,
        origin_ref=cloud_id,
    )
