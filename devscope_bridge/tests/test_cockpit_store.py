from devscope_bridge.whatsapp import cockpit_store


def test_open_creates_tables(tmp_path):
    db = cockpit_store.open_store(tmp_path / "wa.db")
    names = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"chats", "messages", "nudges"} <= names
    db.close()


def test_upsert_and_list_chats(tmp_path):
    db = cockpit_store.open_store(tmp_path / "wa.db")
    cockpit_store.upsert_chat(db, {
        "id": "1@c.us", "name": "Dana", "isGroup": False,
        "lastMessage": {"preview": "hi", "ts": 100, "fromMe": False},
    }, in_scope=True)
    cockpit_store.upsert_messages(db, "1@c.us", [
        {"id": "m1", "author": "1@c.us", "text": "hi", "ts": 100,
         "fromMe": False, "type": "chat"},
    ])
    rows = cockpit_store.list_chats(db)
    assert rows[0]["name"] == "Dana"
    assert rows[0]["last_msg_from_me"] == 0
    assert cockpit_store.recent_messages(db, "1@c.us", 10)[0]["text"] == "hi"
    db.close()


def test_upsert_messages_idempotent(tmp_path):
    db = cockpit_store.open_store(tmp_path / "wa.db")
    msg = {"id": "m1", "author": "1@c.us", "text": "hi", "ts": 100,
           "fromMe": False, "type": "chat"}
    cockpit_store.upsert_messages(db, "1@c.us", [msg])
    cockpit_store.upsert_messages(db, "1@c.us", [msg])
    assert len(cockpit_store.recent_messages(db, "1@c.us", 10)) == 1
    db.close()


def test_mute_preserved_across_upsert(tmp_path):
    db = cockpit_store.open_store(tmp_path / "wa.db")
    chat = {"id": "1@c.us", "name": "Dana", "isGroup": False,
            "lastMessage": {"preview": "hi", "ts": 100, "fromMe": False}}
    cockpit_store.upsert_chat(db, chat, in_scope=True)
    cockpit_store.set_muted(db, "1@c.us", True)
    cockpit_store.upsert_chat(db, chat, in_scope=True)  # re-poll
    assert cockpit_store.list_chats(db)[0]["muted"] == 1
    db.close()
