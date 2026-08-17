from devscope_bridge.whatsapp import nudge_engine

H = 3600


def _chat(**kw):
    base = dict(id="1@c.us", in_scope=1, muted=0, last_msg_ts=0,
                last_msg_from_me=0)
    base.update(kw)
    return base


def test_open_when_last_not_from_me_and_stale():
    chats = [_chat(last_msg_ts=1 * H, last_msg_from_me=0)]
    out = nudge_engine.compute(chats, now=5 * H, threshold_s=3 * H)
    assert [n["chat_id"] for n in out] == ["1@c.us"]


def test_not_open_when_last_from_me():
    chats = [_chat(last_msg_from_me=1)]
    assert nudge_engine.compute(chats, now=10 * H, threshold_s=3 * H) == []


def test_not_open_when_recent():
    chats = [_chat(last_msg_ts=9 * H)]
    assert nudge_engine.compute(chats, now=10 * H, threshold_s=3 * H) == []


def test_scope_and_mute_excluded():
    chats = [_chat(id="a", in_scope=0), _chat(id="b", muted=1)]
    assert nudge_engine.compute(chats, now=10 * H, threshold_s=H) == []


def test_unknown_timestamp_excluded():
    # last_msg_ts==0 (chat not yet loaded) must not become an ancient nudge.
    chats = [_chat(last_msg_ts=0)]
    assert nudge_engine.compute(chats, now=100 * H, threshold_s=H) == []


def test_sorted_oldest_first():
    chats = [_chat(id="new", last_msg_ts=5 * H),
             _chat(id="old", last_msg_ts=1 * H)]
    out = nudge_engine.compute(chats, now=100 * H, threshold_s=H)
    assert [n["chat_id"] for n in out] == ["old", "new"]
