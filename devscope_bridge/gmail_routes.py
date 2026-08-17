"""gmail_routes.py — FastAPI /gm/* router over the Gmail service.

Auth is applied at include_router time in main.py (matching the task_routes
and whatsapp_routes pattern — no per-route auth dependency).
"""
from fastapi import APIRouter
from devscope_bridge.gmail import gmail_service

router = APIRouter(prefix="/gm", tags=["gmail"])


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "data": {"token_configured": gmail_service.token_configured()},
    }


@router.get("/threads")
async def threads(q: str = "in:inbox", limit: int = 25) -> dict:
    """Search Gmail threads by query string (Gmail search syntax)."""
    return await gmail_service.search_threads(q=q, limit=limit)


@router.get("/thread")
async def thread(thread_id: str) -> dict:
    """Fetch a single thread by ID and return parsed subject + messages."""
    return await gmail_service.get_thread(thread_id=thread_id)


@router.get("/labels")
async def labels() -> dict:
    """List all Gmail labels for the authenticated user."""
    return await gmail_service.list_labels()
