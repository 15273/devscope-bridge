"""
task_mcp_server.py — MCP server (stdio) exposing the agent task board to Claude
sessions. Forwards every tool call to the dev_bridge /tasks routes over loopback
so the bridge stays the single SQLite writer.

Claude CLI spawns this as a child process:
  .venv/bin/python -m devscope_bridge.task_mcp_server
"""

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

_TOKEN_FILE = Path.home() / ".dev-bridge" / "token"
_BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:7878")


def _assert_loopback_bridge_url(url: str) -> None:
    """Reject any BRIDGE_URL that doesn't target loopback."""
    loopback_prefixes = (
        "http://127.0.0.1",
        "http://localhost",
        "http://[::1]",
    )
    if not any(url.startswith(p) for p in loopback_prefixes):
        raise RuntimeError(
            f"BRIDGE_URL must target loopback only (got {url!r}). "
            "Set BRIDGE_URL=http://127.0.0.1:7878 or leave unset."
        )


_assert_loopback_bridge_url(_BRIDGE_URL)


def _read_token() -> str:
    if not _TOKEN_FILE.exists():
        raise RuntimeError(f"Bridge token not found at {_TOKEN_FILE}.")
    return _TOKEN_FILE.read_text().strip()


def _actor() -> str | None:
    return os.environ.get("DEVSCOPE_SESSION") or None


async def _call(method: str, path: str, json_body: dict | None = None,
                params: dict | None = None) -> dict[str, Any]:
    token = _read_token()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method, f"{_BRIDGE_URL}{path}",
                json=json_body, params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"Bridge unreachable: {exc}"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "body": resp.text}
    return resp.json()


mcp = FastMCP(
    "task-control",
    instructions=(
        "Read and update the autonomous-agent task board. Managers triage and assign "
        "tasks; workers report progress with task_update and gate sensitive actions "
        "(send/purchase/delete/money) with task_request_approval — which PAUSES the task "
        "until the user approves. Always task_update to 'in_progress' when you start a "
        "worker_unit and to 'done' with a result_summary when finished."
    ),
)


@mcp.tool()
async def task_list(status: str | None = None, domain: str | None = None,
                    assignee: str | None = None) -> dict[str, Any]:
    """List tasks, optionally filtered by status, domain, or assignee session."""
    params = {k: v for k, v in
              {"status": status, "domain": domain, "assignee_session": assignee}.items()
              if v is not None}
    return await _call("GET", "/tasks", params=params)


@mcp.tool()
async def task_create(title: str, kind: str = "worker_unit", detail: str | None = None,
                      domain: str | None = None, parent_id: str | None = None,
                      instruction: str | None = None) -> dict[str, Any]:
    """Create a task. kind: mom_task | domain_task | worker_unit."""
    return await _call("POST", "/tasks", json_body={
        "title": title, "kind": kind, "detail": detail, "domain": domain,
        "parent_id": parent_id, "instruction": instruction, "source": "chat",
    })


@mcp.tool()
async def task_update(task_id: str, status: str | None = None, note: str | None = None,
                      result_summary: str | None = None, domain: str | None = None,
                      instruction: str | None = None,
                      artifact_path: str | None = None) -> dict[str, Any]:
    """Update a task's status/result and optionally append a progress note."""
    return await _call("POST", f"/tasks/{task_id}/update", json_body={
        "status": status, "note": note, "result_summary": result_summary,
        "domain": domain, "instruction": instruction, "artifact_path": artifact_path,
        "assignee_session": _actor(),
    })


@mcp.tool()
async def task_request_approval(task_id: str, action: str,
                                payload: dict | None = None) -> dict[str, Any]:
    """Pause a task for human approval before a sensitive action (send/purchase/delete/money)."""
    return await _call("POST", f"/tasks/{task_id}/request-approval",
                       json_body={"action": action, "payload": payload})


@mcp.tool()
async def task_ask_user(task_id: str, question: str,
                        options: list[str] | None = None) -> dict[str, Any]:
    """Ask the user a blocking question — pauses the task until they answer.
    The answer is appended to the task instruction and the task is requeued."""
    return await _call("POST", f"/tasks/{task_id}/request-approval",
                       json_body={"action": "question",
                                  "payload": {"question": question,
                                              "options": options or []}})


@mcp.tool()
async def task_log(task_id: str, message: str) -> dict[str, Any]:
    """Append a free-text progress line to a task's timeline."""
    return await _call("POST", f"/tasks/{task_id}/log",
                       json_body={"message": message, "actor": _actor()})


@mcp.tool()
async def task_save_mom_report(report: str) -> dict[str, Any]:
    """Save a short MoM triage summary for the task board UI."""
    return await _call("POST", "/orchestrator/mom-report", json_body={"report": report})


@mcp.tool()
async def schedule_playbook_update(schedule_id: int, patch: dict) -> dict[str, Any]:
    """Merge reusable page knowledge into a recurring schedule's playbook memory."""
    return await _call("POST", f"/schedules/{schedule_id}/playbook",
                       json_body={"patch": patch})


@mcp.tool()
async def schedule_list() -> dict[str, Any]:
    """List recurring schedules and their next run times."""
    return await _call("GET", "/schedules")


@mcp.tool()
async def schedule_setup_update(draft_id: str, patch: dict) -> dict[str, Any]:
    """Update the in-progress schedule setup draft playbook (workflow, selectors, notes)."""
    return await _call("POST", f"/schedules/setup/drafts/{draft_id}/playbook",
                       json_body={"patch": patch})


@mcp.tool()
async def schedule_setup_set_instruction(draft_id: str, instruction: str) -> dict[str, Any]:
    """Set the per-run instruction text on an in-progress schedule setup draft."""
    return await _call("POST", f"/schedules/setup/drafts/{draft_id}/instruction",
                       json_body={"instruction": instruction})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    mcp.run(transport="stdio")

