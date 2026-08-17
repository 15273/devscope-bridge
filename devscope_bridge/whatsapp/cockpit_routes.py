"""cockpit_routes.py — FastAPI routes for the WhatsApp Copilot cockpit.

Mounted at /wa/cockpit/* in main.py (behind require_auth).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from devscope_bridge.whatsapp import (
    cockpit_config,
    cockpit_store,
    cockpit_sync,
    whatsapp_engine,
)

router = APIRouter(prefix="/wa/cockpit", tags=["cockpit"])

_DB = Path.home() / ".dev-bridge" / "wa_cockpit.db"
_CFG = Path.home() / ".dev-bridge" / "wa_cockpit_config.json"


def _db():
    return cockpit_store.open_store(_DB)


@router.get("/nudges")
async def get_nudges() -> dict:
    """Return all open nudges (chats waiting on a reply)."""
    db = _db()
    rows = db.execute(
        """SELECT n.chat_id, n.since_ts, n.state, c.name, c.is_group,
                  c.last_msg_preview
           FROM nudges n
           JOIN chats c ON c.id = n.chat_id
           WHERE n.state = 'open'
           ORDER BY n.since_ts ASC"""
    ).fetchall()
    db.close()
    return {"ok": True, "data": [dict(r) for r in rows]}


@router.get("/settings")
async def get_settings() -> dict:
    return {"ok": True, "data": cockpit_config.load(_CFG)}


class Settings(BaseModel):
    threshold_hours: int | None = None
    dm_in_scope: bool | None = None
    group_allowlist: list[str] | None = None
    blacklist: list[str] | None = None
    poll_interval_s: int | None = None


@router.post("/settings")
async def set_settings(body: Settings) -> dict:
    cfg = cockpit_config.load(_CFG)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    cfg.update(updates)
    cockpit_config.save(_CFG, cfg)
    return {"ok": True, "data": cfg}


class ChatIdBody(BaseModel):
    chat_id: str


@router.post("/handled")
async def mark_handled(body: ChatIdBody) -> dict:
    """Mark a nudge as handled (user dealt with it)."""
    db = _db()
    db.execute("UPDATE nudges SET state='handled' WHERE chat_id=?", (body.chat_id,))
    db.commit()
    db.close()
    return {"ok": True}


@router.post("/mute")
async def mute_chat(body: ChatIdBody) -> dict:
    """Mute a chat so it never appears in nudges."""
    db = _db()
    cockpit_store.set_muted(db, body.chat_id, True)
    db.close()
    return {"ok": True}


@router.post("/draft")
async def draft_reply(body: ChatIdBody) -> dict:
    """Return AI-suggested reply candidates for a chat."""
    db = _db()
    msgs = [dict(r) for r in cockpit_store.recent_messages(db, body.chat_id, 12)]
    db.close()
    from devscope_bridge.whatsapp import cockpit_drafter
    candidates = await cockpit_drafter.suggest(list(reversed(msgs)))
    return {"ok": True, "data": {"candidates": candidates}}


class HistoryTurn(BaseModel):
    role: str
    content: str


class AskBody(BaseModel):
    question: str
    chat_id: str | None = None
    chat_name: str | None = None
    session: str | None = None
    agent: str = Field(default="cursor", pattern="^(claude|cursor)$")
    model: str | None = None
    mode: str | None = None
    history: list[HistoryTurn] = Field(default_factory=list)
    dms_only: bool | None = None
    groups_only: bool | None = None


# Question words to ignore when guessing a chat name from free text.
_STOPWORDS = {
    "מה", "מי", "האם", "כתב", "כתבה", "אמר", "אמרה", "ענה", "לי", "לו", "לה",
    "היום", "אתמול", "עם", "של", "את", "כדאי", "לענות", "קורה", "בצ'אט",
    "בצאט", "בצׄאט", "ומה", "אתה", "ממליץ", "צריך", "the", "what", "did", "say",
}


def _name_candidates(chat_name: str | None, question: str) -> list[str]:
    """Yield possible chat-name needles: explicit name first, then question words."""
    out: list[str] = []
    if chat_name:
        out.append(chat_name)
    for word in question.replace("?", " ").replace("׳", "").split():
        w = word.strip(".,!\"'")
        if len(w) >= 2 and w not in _STOPWORDS and w not in out:
            out.append(w)
    return out


@router.get("/health")
async def cockpit_health(session: str | None = Query(None)) -> dict:
    """Live WhatsApp Store probe + SQLite mirror stats."""
    db = _db()
    chat_count = db.execute("SELECT COUNT(*) AS n FROM chats").fetchone()["n"]
    msg_count = db.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
    db.close()
    live = await cockpit_sync.wa_store_health(session)
    return {
        "ok": True,
        "data": {
            "live": live,
            "mirror": {"chats": chat_count, "messages": msg_count},
        },
    }


class SyncBody(BaseModel):
    chat_id: str | None = None
    session: str | None = None


@router.post("/sync")
async def sync_mirror(body: SyncBody) -> dict:
    """Refresh SQLite mirror from live WhatsApp (one chat or full chat list)."""
    cfg = cockpit_config.load(_CFG)
    db = _db()
    session = await cockpit_sync.pick_wa_session(body.session)
    if body.chat_id:
        msgs, err = await cockpit_sync.hydrate_chat_messages(
            db, body.chat_id, session, cfg, force=True,
        )
        db.close()
        return {"ok": err is None, "data": {"messages": len(msgs)}, "error": err}
    res = await whatsapp_engine.list_chats(limit=200, session=session)
    if not res.get("ok"):
        db.close()
        return {"ok": False, "error": res.get("error", "list_chats failed")}
    synced = 0
    for chat in res.get("data") or []:
        in_scope = cockpit_config.is_in_scope(
            cfg, chat["id"], is_group=chat.get("isGroup", False),
        )
        cockpit_store.upsert_chat(db, chat, in_scope=in_scope)
        synced += 1
    db.close()
    return {"ok": True, "data": {"chats": synced}}


@router.post("/ask")
async def ask_assistant(body: AskBody) -> dict:
    """Answer a question about a chat or the unread inbox."""
    from devscope_bridge.whatsapp import cockpit_assistant, cockpit_inbox

    history = [h.model_dump() for h in body.history]
    question = cockpit_inbox.effective_question(body.question, history)
    filters = cockpit_inbox.parse_filters(question, history)
    dms_only = body.dms_only if body.dms_only is not None else filters["dms_only"]
    groups_only = (
        body.groups_only if body.groups_only is not None else filters["groups_only"]
    )
    use_inbox = cockpit_inbox.should_use_inbox(
        question,
        body.chat_id,
        history,
        dms_only=dms_only,
        groups_only=groups_only,
    )

    if use_inbox:
        chats, total_unread, err = await cockpit_inbox.fetch_unread_inbox(
            body.session,
            dms_only=dms_only,
            groups_only=groups_only,
        )
        if err:
            return {"ok": True, "data": {
                "answer": err,
                "chat_id": None,
                "chat_name": None,
                "inbox": True,
            }}
        inbox_block = cockpit_inbox.format_inbox_block(
            chats,
            dms_only=dms_only,
            groups_only=groups_only,
            total_unread_before_filter=total_unread,
        )
        answer = await cockpit_assistant.ask_inbox(
            question,
            inbox_block,
            history=history,
            agent=body.agent,
            model=body.model,
            mode=body.mode,
            session_name=body.session,
        )
        if not answer.strip():
            answer = "לא הצלחתי לקבל תשובה מה-agent. נסה שוב או החלף agent/model."
        filter_label = "dms" if dms_only else "groups" if groups_only else "all"
        return {"ok": True, "data": {
            "answer": answer,
            "chat_id": None,
            "chat_name": None,
            "inbox": True,
            "filter": filter_label,
            "unread_count": len(chats),
        }}

    db = _db()
    cfg = cockpit_config.load(_CFG)
    chat_id = body.chat_id
    if not chat_id:
        for needle in _name_candidates(body.chat_name, body.question):
            matches = cockpit_store.find_chats_by_name(db, needle, limit=1)
            if matches:
                chat_id = matches[0]["id"]
                break
        if not chat_id and body.session:
            session = await cockpit_sync.pick_wa_session(body.session)
            search_q = body.chat_name or body.question.split()[0] if body.question else ""
            if search_q and session:
                found = await whatsapp_engine.search(search_q[:40], session=session)
                if found.get("ok") and found.get("data"):
                    chat_id = found["data"][0].get("id")
                    if chat_id:
                        await cockpit_sync.upsert_chat_meta(db, chat_id, session, cfg)
    if not chat_id:
        names = [r["name"] for r in cockpit_store.list_chats(db)[:8] if r["name"]]
        db.close()
        hint = "، ".join(names)
        return {"ok": True, "data": {"answer": (
            "לא הצלחתי לזהות על איזה צ'אט מדובר. לחץ \"התייעץ\" על צ'אט מהרשימה, "
            "או ציין שם מדויק יותר. צ'אטים אחרונים: " + hint
        ), "chat_id": None, "chat_name": None}}
    chat = cockpit_store.get_chat(db, chat_id)
    name = chat["name"] if chat else (body.chat_name or chat_id)
    msgs, sync_err = await cockpit_sync.hydrate_chat_messages(
        db, chat_id, body.session, cfg, limit=40, force=not bool(cockpit_store.recent_messages(db, chat_id, 1)),
    )
    db.close()
    if not msgs and sync_err:
        return {"ok": True, "data": {
            "answer": (
                f"לא הצלחתי לקרוא הודעות מ-WhatsApp ({sync_err}). "
                "ודא ש-web.whatsapp.com פתוח ומחובר, וש-DevScope connected."
            ),
            "chat_id": chat_id,
            "chat_name": name,
        }}
    answer = await cockpit_assistant.ask(
        name, msgs, question,
        history=history,
        agent=body.agent,
        model=body.model,
        mode=body.mode,
        session_name=body.session,
    )
    if not answer.strip():
        answer = "לא הצלחתי לקבל תשובה מה-agent. נסה שוב או החלף agent/model."
    return {"ok": True, "data": {"answer": answer, "chat_id": chat_id, "chat_name": name}}


class SendBody(BaseModel):
    chat_id: str
    text: str


@router.post("/send")
async def send_message(body: SendBody) -> dict:
    """Send a message and mark the nudge handled on success."""
    # session=None → engine routes via the last profile known to reach WhatsApp.
    res = await whatsapp_engine.send_message(body.chat_id, body.text)
    if res.get("ok"):
        db = _db()
        db.execute("UPDATE nudges SET state='handled' WHERE chat_id=?", (body.chat_id,))
        db.commit()
        db.close()
    return res
