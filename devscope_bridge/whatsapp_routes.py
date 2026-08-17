"""whatsapp_routes.py — FastAPI /wa/* router over the WhatsApp engine.

Auth is applied at include_router time in main.py (matching the task_routes pattern).
"""
from fastapi import APIRouter
from devscope_bridge.whatsapp import whatsapp_engine

router = APIRouter(prefix="/wa", tags=["whatsapp"])


@router.get("/chats")
async def chats(filter: str | None = None, limit: int = 50, session: str | None = None) -> dict:
    """List WhatsApp chats; optionally filter by 'unread'."""
    return await whatsapp_engine.list_chats(filter=filter, limit=limit, session=session)


@router.get("/messages")
async def messages(chat_id: str, limit: int = 30, session: str | None = None) -> dict:
    """Get recent messages from a chat by ID."""
    return await whatsapp_engine.get_messages(chat_id=chat_id, limit=limit, session=session)


@router.get("/search")
async def search(query: str, session: str | None = None) -> dict:
    """Search chats by name substring."""
    return await whatsapp_engine.search(query=query, session=session)
