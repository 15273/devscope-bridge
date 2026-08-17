"""
invoke_routes.py — POST /invoke: run a registry capability, return a sync result.

Thin HTTP shim over capability_router.invoke(); called by devscope_mcp_server
(the `devscope_invoke` MCP tool inside Claude sessions).  Auth is attached at
include time in main.py, like every other bridge router.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from devscope_bridge import capability_router

router = APIRouter()


class InvokeRequest(BaseModel):
    capability: str
    task: str
    session: str | None = None
    wait: bool = True
    timeout_s: float | None = None


@router.post("/invoke")
async def post_invoke(body: InvokeRequest) -> dict:
    return await capability_router.invoke(
        body.capability, body.task,
        session=body.session, wait=body.wait, timeout_s=body.timeout_s,
    )
