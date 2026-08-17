// whatsapp_store_inject.js — runs in MAIN world on web.whatsapp.com.
// Returns a JSON-serializable object (or Promise thereof). Never throws across
// the boundary. Async to support write ops (send / mark_read) that need await.
(async function (op, params) {
  // Collect every webpack module keyed by its (string) module id, the same
  // way @pedroslopez/moduleraid does inside whatsapp-web.js.
  function collectModules() {
    const chunk = window.webpackChunkwhatsapp_web_client || window.webpackChunkbuild;
    if (!chunk) return null;
    const id = "wa_grab_" + Date.now();
    const mods = {};
    chunk.push([[id], {}, (req) => {
      for (const k of Object.keys(req.m)) {
        try { mods[k] = req(k); } catch (e) {}
      }
    }]);
    return mods;
  }

  // Modern WhatsApp Web aggregates model collections in the named module
  // 'WAWebCollections' (mirrors wwebjs `window.require('WAWebCollections')`).
  // Fall back to individual collection modules, then to the legacy structural
  // predicates for older builds.
  function pickStore(mods) {
    const collections = mods["WAWebCollections"];
    let Chat = collections && collections.Chat;
    let Msg = collections && collections.Msg;
    if (!Chat && mods["WAWebChatCollection"]) Chat = mods["WAWebChatCollection"].ChatCollection;
    if (!Msg && mods["WAWebMsgCollection"]) Msg = mods["WAWebMsgCollection"].MsgCollection;
    if (!Chat) {
      const find = (pred) => Object.values(mods).find(pred);
      const cm = find((m) => m && m.Chat && m.Chat.modelClass) || find((m) => m && m.default && m.default.Chat);
      Chat = cm && (cm.Chat || cm.default?.Chat);
      const mm = find((m) => m && m.Msg && m.Msg.modelClass);
      if (!Msg) Msg = mm && mm.Msg;
    }
    return Chat ? { Chat: Chat, Msg: Msg || null } : null;
  }

  // Resolve model collections by name via the natively-exposed module loader.
  // Modern WhatsApp Web (Comet, version 2.3000+) exposes window.require(moduleId)
  // in the MAIN world — this is how whatsapp-web.js reaches the Store on current
  // builds. The chunk-push enumeration above is the legacy fallback.
  function fromRequire() {
    const req = window.require;
    if (typeof req !== "function") return null;
    let Chat, Msg;
    try { const c = req("WAWebCollections"); Chat = c && c.Chat; Msg = c && c.Msg; } catch (e) {}
    if (!Chat) { try { Chat = req("WAWebChatCollection").ChatCollection; } catch (e) {} }
    if (!Msg) { try { Msg = req("WAWebMsgCollection").MsgCollection; } catch (e) {} }
    return Chat ? { Chat: Chat, Msg: Msg || null } : null;
  }

  function grabStore() {
    try {
      if (window.__WA_STORE__) return window.__WA_STORE__;
      let store = fromRequire();
      if (!store) {
        const mods = collectModules();
        if (mods) { window.__WA_MODS__ = mods; store = pickStore(mods); }
      }
      if (store) window.__WA_STORE__ = store;
      return store;
    } catch (e) { return null; }
  }

  function chatToJson(c) {
    const serialized = c.id?._serialized || String(c.id);
    return {
      id: serialized,
      name: c.formattedTitle || c.name || c.contact?.name || "",
      // Modern WhatsApp Web no longer exposes a reliable `isGroup` flag on the
      // chat model — derive it from the JID server ("@g.us").
      isGroup: !!c.isGroup || c.id?.server === "g.us" || /@g\.us$/.test(serialized),
      unreadCount: c.unreadCount || 0,
      pinned: !!c.pin,
      muted: !!c.mute?.isMuted,
      lastMessage: c.msgs?.last?.() ? {
        preview: (c.msgs.last().body || "").slice(0, 120),
        ts: c.msgs.last().t || 0,
        fromMe: !!c.msgs.last().id?.fromMe,
      } : null,
    };
  }

  try {
    const store = grabStore();
    if (!store) return { ok: false, error: "store_unavailable" };

    if (op === "list_chats") {
      const limit = params.limit || 50;
      let chats = store.Chat.getModelsArray ? store.Chat.getModelsArray() : store.Chat.models || [];
      if (params.filter === "unread") chats = chats.filter((c) => (c.unreadCount || 0) > 0);
      chats = chats.slice(0, limit).map(chatToJson);
      return { ok: true, data: chats };
    }

    if (op === "get_messages") {
      const chat = store.Chat.get(params.chatId);
      if (!chat) return { ok: false, error: "chat_not_found" };
      const limit = params.limit || 30;
      const msgs = (chat.msgs?.getModelsArray?.() || chat.msgs?.models || []).slice(-limit).map((m) => ({
        id: m.id?._serialized || String(m.id),
        fromMe: !!m.id?.fromMe,
        author: m.author?._serialized || m.from?._serialized || "",
        type: m.type || "chat",
        text: m.body || m.caption || "",
        ts: m.t || 0,
        quoted: m.quotedMsg ? (m.quotedMsg.body || "").slice(0, 80) : null,
        hasMedia: !!m.isMedia,
      }));
      return { ok: true, data: msgs };
    }

    if (op === "search") {
      const q = (params.query || "").toLowerCase();
      const chats = (store.Chat.getModelsArray?.() || store.Chat.models || [])
        .filter((c) => (c.formattedTitle || c.name || "").toLowerCase().includes(q))
        .slice(0, 20).map(chatToJson);
      return { ok: true, data: chats };
    }

    if (op === "send") {
      try {
        const chat = store.Chat.get(params.chatId);
        if (!chat) return { ok: false, error: "chat_not_found" };
        const MsgKey = window.require("WAWebMsgKey");
        const UserPrefs = window.require("WAWebUserPrefsMeUser");
        const Wid = window.require("WAWebWidFactory");
        const Eph = window.require("WAWebGetEphemeralFieldsMsgActionsUtils");
        const Send = window.require("WAWebSendMsgChatAction");
        const newId = await MsgKey.newId();
        const meLid = UserPrefs.getMaybeMeLidUser();
        const mePn = UserPrefs.getMaybeMePnUser();
        let from = (chat.id.isLid && chat.id.isLid()) ? meLid : mePn;
        let participant;
        if (chat.id.isGroup && chat.id.isGroup()) {
          from = (chat.groupMetadata && chat.groupMetadata.isLidAddressingMode) ? meLid : mePn;
          participant = Wid.asUserWidOrThrow(from);
        }
        const newMsgKey = new MsgKey({ from, to: chat.id, id: newId, participant, selfDir: "out" });
        const message = {
          id: newMsgKey, ack: 0, body: params.text, from, to: chat.id,
          local: true, self: "out", t: Math.floor(Date.now() / 1000),
          isNewMsg: true, type: "chat", ...Eph.getEphemeralFields(chat),
        };
        const [msgPromise] = Send.addAndSendMsgToChat(chat, message);
        await msgPromise;
        return { ok: true, data: { sent: true } };
      } catch (e) {
        return { ok: false, error: String(e && e.message || e) };
      }
    }

    if (op === "mark_read") {
      try {
        const chat = store.Chat.get(params.chatId);
        if (!chat) return { ok: false, error: "chat_not_found" };
        const Seen = window.require("WAWebUpdateUnreadChatAction");
        await Seen.sendSeen(chat, false);
        return { ok: true, data: { read: true } };
      } catch (e) {
        try {
          const chat = store.Chat.get(params.chatId);
          if (chat && typeof chat.sendSeen === "function") {
            await chat.sendSeen();
            return { ok: true, data: { read: true } };
          }
        } catch (_) {}
        return { ok: false, error: String(e && e.message || e) };
      }
    }

    return { ok: false, error: "unknown_op:" + op };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e) };
  }
});
