"""
plugin_store_routes.py — REST surface for the DevScope plugin store.

GET  /store/catalog?q=   — featured + live MCP-registry search
GET  /store/state        — installed plugins with live status
POST /store/install      — register a remote MCP + enable it
POST /store/login        — start the browser OAuth flow for a plugin
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from devscope_bridge import plugin_store

router = APIRouter(prefix="/store", tags=["plugin-store"])


class InstallBody(BaseModel):
    id: str
    title: str
    url: str


class LoginBody(BaseModel):
    id: str


@router.get("/catalog")
async def catalog(q: str = "") -> dict:
    return {"items": await plugin_store.search_catalog(q)}


@router.get("/state")
async def state() -> dict:
    return await plugin_store.state()


@router.post("/install")
async def install(body: InstallBody) -> dict:
    return await plugin_store.install(body.id, body.title, body.url)


@router.post("/login")
async def login(body: LoginBody) -> dict:
    return await plugin_store.start_login(body.id)
