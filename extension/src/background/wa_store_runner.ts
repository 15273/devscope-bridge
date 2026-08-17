/**
 * wa_store_runner.ts — runs the WhatsApp Store inject in world:'MAIN'
 * on the resolved WA tab via chrome.scripting.executeScript.
 *
 * CANONICAL REFERENCE: devscope_bridge/whatsapp/whatsapp_store_inject.js
 * is the canonical copy of this inject logic (used by the Python-side
 * registry/docs). The logic below must be kept in sync with that file.
 * Do NOT use new Function / eval here — WhatsApp Web ships a strict
 * script-src CSP without 'unsafe-eval', so runtime eval inside the page
 * world will be blocked. chrome.scripting.executeScript serialises `func`
 * as source and injects it before execution, so it is exempt from page CSP.
 */

type WaParams = {
  chatId?: string;
  query?: string;
  filter?: string;
  limit?: number;
  text?: string;
};

type WaResult = { ok: boolean; data?: unknown; error?: string };

export async function runWaStore(
  tabId: number,
  op: string,
  params: Record<string, unknown>,
): Promise<WaResult> {
  try {
    const tab = await chrome.tabs.get(tabId);
    const url = tab.url ?? '';
    if (!/^https:\/\/web\.whatsapp\.com/i.test(url)) {
      return {
        ok: false,
        error: 'not_whatsapp_tab',
        data: { url, title: tab.title ?? '' },
      };
    }
  } catch {
    return { ok: false, error: 'tab_not_found' };
  }

  const [res] = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    func: async (o: string, p: WaParams): Promise<WaResult> => {
      const g: any =
        typeof window !== 'undefined'
          ? window
          : typeof self !== 'undefined'
            ? self
            : (globalThis as any);
      function diag(): Record<string, unknown> {
        const mods: Record<string, any> = g.__WA_MODS__ || {};
        const collections = mods['WAWebCollections'];
        return {
          ctx_typeof_window: typeof window,
          ctx_typeof_self: typeof self,
          href: (() => { try { return g.location?.href ?? null; } catch { return null; } })(),
          webpack_keys: (() => {
            try { return Object.keys(g).filter((k) => k.startsWith('webpackChunk')); }
            catch { return null; }
          })(),
          has_window_require: typeof g.require,
          require_collections_keys: (() => {
            try { const c = g.require('WAWebCollections'); return c ? Object.keys(c).slice(0, 40) : null; }
            catch (e) { return 'ERR:' + String((e as Error)?.message || e); }
          })(),
          mods_count: Object.keys(mods).length,
          has_collections: !!collections,
          collections_keys: collections ? Object.keys(collections).slice(0, 40) : null,
          collection_module_keys: Object.keys(mods).filter((k) => /Collection/i.test(k)).slice(0, 40),
        };
      }
      // Collect every webpack module keyed by its (string) module id, the same
      // way @pedroslopez/moduleraid does inside whatsapp-web.js.
      function collectModules(): Record<string, any> | null {
        const chunk: any = g.webpackChunkwhatsapp_web_client || g.webpackChunkbuild;
        if (!chunk) return null;
        const id = 'wa_grab_' + Date.now();
        const mods: Record<string, any> = {};
        chunk.push([[id], {}, (req: any) => {
          for (const k of Object.keys(req.m)) {
            try { mods[k] = req(k); } catch (_) {}
          }
        }]);
        return mods;
      }
      // Modern WhatsApp Web aggregates model collections in the named module
      // 'WAWebCollections' (mirrors wwebjs `window.require('WAWebCollections')`).
      // Fall back to individual collection modules, then to the legacy
      // structural predicates for older builds.
      function pickStore(mods: Record<string, any>): { Chat: any; Msg: any } | null {
        const collections = mods['WAWebCollections'];
        let Chat: any = collections && collections.Chat;
        let Msg: any = collections && collections.Msg;
        if (!Chat && mods['WAWebChatCollection']) Chat = mods['WAWebChatCollection'].ChatCollection;
        if (!Msg && mods['WAWebMsgCollection']) Msg = mods['WAWebMsgCollection'].MsgCollection;
        if (!Chat) {
          const find = (pred: (m: any) => boolean) => Object.values(mods).find(pred);
          const cm: any =
            find((m) => m && m.Chat && m.Chat.modelClass) ||
            find((m) => m && m.default && m.default.Chat);
          Chat = cm && (cm.Chat || cm.default?.Chat);
          const mm: any = find((m) => m && m.Msg && m.Msg.modelClass);
          if (!Msg) Msg = mm && mm.Msg;
        }
        return Chat ? { Chat, Msg: Msg || null } : null;
      }
      // Resolve model collections by name via the natively-exposed module
      // loader. Modern WhatsApp Web (Comet, version 2.3000+) exposes
      // window.require(moduleId) in the MAIN world — this is how whatsapp-web.js
      // reaches the Store on current builds.
      function fromRequire(): { Chat: any; Msg: any } | null {
        const req: any = g.require;
        if (typeof req !== 'function') return null;
        let Chat: any;
        let Msg: any;
        try { const c = req('WAWebCollections'); Chat = c && c.Chat; Msg = c && c.Msg; } catch (_) {}
        if (!Chat) { try { Chat = req('WAWebChatCollection').ChatCollection; } catch (_) {} }
        if (!Msg) { try { Msg = req('WAWebMsgCollection').MsgCollection; } catch (_) {} }
        return Chat ? { Chat, Msg: Msg || null } : null;
      }
      function grabStore(): { Chat: any; Msg: any } | null {
        try {
          if (g.__WA_STORE__) return g.__WA_STORE__;
          let store = fromRequire();
          if (!store) {
            const mods = collectModules();
            if (mods) { g.__WA_MODS__ = mods; store = pickStore(mods); }
          }
          if (store) g.__WA_STORE__ = store;
          return store;
        } catch (_) { return null; }
      }

      function chatToJson(c: any) {
        const serialized = c.id?._serialized || String(c.id);
        return {
          id: serialized,
          name: c.formattedTitle || c.name || c.contact?.name || '',
          // Modern WhatsApp Web no longer exposes a reliable `isGroup` flag on
          // the chat model — derive it from the JID server (`@g.us`).
          isGroup: !!c.isGroup || c.id?.server === 'g.us' || /@g\.us$/.test(serialized),
          unreadCount: c.unreadCount || 0,
          pinned: !!c.pin,
          muted: !!c.mute?.isMuted,
          lastMessage: c.msgs?.last?.() ? {
            preview: (c.msgs.last().body || '').slice(0, 120),
            ts: c.msgs.last().t || 0,
            fromMe: !!c.msgs.last().id?.fromMe,
          } : null,
        };
      }

      try {
        const store = grabStore();
        if (!store) return { ok: false, error: 'store_unavailable', data: diag() as any };

        if (o === 'list_chats') {
          const limit = p.limit || 50;
          let chats: any[] = store.Chat.getModelsArray
            ? store.Chat.getModelsArray()
            : store.Chat.models || [];
          if (p.filter === 'unread') chats = chats.filter((c) => (c.unreadCount || 0) > 0);
          return { ok: true, data: chats.slice(0, limit).map(chatToJson) };
        }

        if (o === 'get_messages') {
          const chat = store.Chat.get(p.chatId);
          if (!chat) return { ok: false, error: 'chat_not_found' };
          const limit = p.limit || 30;
          const msgs = (
            chat.msgs?.getModelsArray?.() || chat.msgs?.models || []
          ).slice(-limit).map((m: any) => ({
            id: m.id?._serialized || String(m.id),
            fromMe: !!m.id?.fromMe,
            author: m.author?._serialized || m.from?._serialized || '',
            type: m.type || 'chat',
            text: m.body || m.caption || '',
            ts: m.t || 0,
            quoted: m.quotedMsg ? (m.quotedMsg.body || '').slice(0, 80) : null,
            hasMedia: !!m.isMedia,
          }));
          return { ok: true, data: msgs };
        }

        if (o === 'search') {
          const q = (p.query || '').toLowerCase();
          const chats = (store.Chat.getModelsArray?.() || store.Chat.models || [])
            .filter((c: any) =>
              (c.formattedTitle || c.name || '').toLowerCase().includes(q),
            )
            .slice(0, 20)
            .map(chatToJson);
          return { ok: true, data: chats };
        }

        if (o === 'send') {
          try {
            const chat = store.Chat.get(p.chatId);
            if (!chat) return { ok: false, error: 'chat_not_found' };
            const MsgKey: any = g.require('WAWebMsgKey');
            const UserPrefs: any = g.require('WAWebUserPrefsMeUser');
            const Wid: any = g.require('WAWebWidFactory');
            const Eph: any = g.require('WAWebGetEphemeralFieldsMsgActionsUtils');
            const Send: any = g.require('WAWebSendMsgChatAction');
            const newId = await MsgKey.newId();
            const meLid = UserPrefs.getMaybeMeLidUser();
            const mePn = UserPrefs.getMaybeMePnUser();
            let from: any = (chat.id.isLid && chat.id.isLid()) ? meLid : mePn;
            let participant: any;
            if (chat.id.isGroup && chat.id.isGroup()) {
              from = (chat.groupMetadata && chat.groupMetadata.isLidAddressingMode) ? meLid : mePn;
              participant = Wid.asUserWidOrThrow(from);
            }
            const newMsgKey = new MsgKey({ from, to: chat.id, id: newId, participant, selfDir: 'out' });
            const message: any = {
              id: newMsgKey, ack: 0, body: p.text ?? '', from, to: chat.id,
              local: true, self: 'out', t: Math.floor(Date.now() / 1000),
              isNewMsg: true, type: 'chat', ...Eph.getEphemeralFields(chat),
            };
            const [msgPromise] = Send.addAndSendMsgToChat(chat, message);
            await msgPromise;
            return { ok: true, data: { sent: true } };
          } catch (e) {
            return { ok: false, error: String((e as Error)?.message || e) };
          }
        }

        if (o === 'mark_read') {
          try {
            const chat = store.Chat.get(p.chatId);
            if (!chat) return { ok: false, error: 'chat_not_found' };
            const Seen: any = g.require('WAWebUpdateUnreadChatAction');
            await Seen.sendSeen(chat, false);
            return { ok: true, data: { read: true } };
          } catch (e) {
            try {
              const chat = store.Chat.get(p.chatId);
              if (chat && typeof (chat as any).sendSeen === 'function') {
                await (chat as any).sendSeen();
                return { ok: true, data: { read: true } };
              }
            } catch (_) {}
            return { ok: false, error: String((e as Error)?.message || e) };
          }
        }

        return { ok: false, error: 'unknown_op:' + o };
      } catch (e) {
        return { ok: false, error: String((e as Error)?.message || e) };
      }
    },
    args: [op, params as WaParams],
  });
  return (res?.result as WaResult) ?? { ok: false, error: 'no_result' };
}
