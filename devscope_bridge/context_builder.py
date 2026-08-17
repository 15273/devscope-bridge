"""
context_builder.py — Build context preamble strings from MessageContext.
"""

from devscope_bridge.models import MessageContext

_PREAMBLE_HARD_CAP = 2500  # approximate characters (~625 tokens)


def build_context_preamble(context: MessageContext | None) -> str:
    """Build a concise CONTEXT PREAMBLE string from a MessageContext.

    Caps total length to ~1500 chars so we don't blow the prompt budget.
    Returns empty string when context is None or empty.
    """
    if not context:
        return ""

    parts: list[str] = []

    if context.boundTab:
        bt = context.boundTab
        parts.append(
            f"[BROWSER TAB BOUND] tab_id={bt.tabId} window_id={bt.windowId} "
            f"title={bt.title[:120]!r} url={bt.url}"
        )
        parts.append(
            "DevScope is bound to this tab in ANY Chrome window. "
            "Use browser-control MCP tools WITHOUT tab_id to control it "
            "(browser_list_tabs, browser_snapshot, browser_click, browser_fill, …). "
            "Work in the bound tab in the BACKGROUND — do NOT call browser_focus_tab "
            "unless the user explicitly asks to see the page. "
            "Open new URLs with browser_new_page (background tab) and bind that tab_id. "
            "Navigate/click/snapshot work without stealing the user's active tab. "
            "After browser_snapshot, prefer clicking @ref numbers from the snapshot over fragile CSS selectors."
        )

    has_notes = any(getattr(el, "note", None) for el in context.elements)

    for el in context.elements:
        # Elements with a note are explicit edit targets — make the request clear.
        label = "[EDIT TARGET]" if getattr(el, "note", None) else "[ELEMENT]"
        chunk = label
        if getattr(el, "note", None):
            chunk += f" change={el.note[:200]!r}"
        if getattr(el, "editRef", None):
            chunk += f' anchor=[data-edit-ref="{el.editRef}"]'
        chunk += f" selector={el.selector} tag={el.tag}"
        if el.ariaRole:
            chunk += f" role={el.ariaRole!r}"
        if el.ariaName:
            chunk += f" ariaName={el.ariaName[:120]!r}"
        if getattr(el, "domChain", None):
            chunk += f" domChain={' > '.join(el.domChain)}"
        if el.text:
            chunk += f" text={el.text[:120]!r}"
        if el.outerHTML:
            chunk += f" outerHTML={el.outerHTML[:300]!r}"
        if el.cssSnapshot:
            chunk += f" css={el.cssSnapshot}"
        if el.boundingBox:
            chunk += f" bbox={el.boundingBox}"
        if getattr(el, "frameUrl", None):
            chunk += f" frame={el.frameUrl}"
        if getattr(el, "screenshotSnippet", None):
            chunk += " screenshotSnippet=attached"
        parts.append(chunk)

    for att in context.attachments:
        # Image attachments are sent to the model as real image content blocks
        # (see extract_image_blocks); here we only leave a short textual marker
        # so the giant base64 data URL never bloats the prompt preamble.
        if att.kind == "image":
            parts.append(f"[IMAGE attached: {att.label!r} — see the attached image above]")
            continue
        chunk = f"[ATTACHMENT kind={att.kind} label={att.label!r}"
        if att.url:
            chunk += f" url={att.url}"
        if att.data is not None:
            chunk += _summarise_attachment_data(att.kind, att.data)
        chunk += "]"
        parts.append(chunk)

    if not parts:
        return ""

    header = "--- PAGE CONTEXT ---"
    if has_notes:
        header += (
            "\nThe user annotated specific page elements with changes they want. "
            "Each [EDIT TARGET] has a `change=` instruction and a stable "
            '`data-edit-ref` anchor — use it (e.g. document.querySelector('
            "'[data-edit-ref=\"...\"]')) to locate the exact element in the source."
        )
    preamble = header + "\n" + "\n".join(parts) + "\n--- END CONTEXT ---\n\n"
    if len(preamble) > _PREAMBLE_HARD_CAP:
        preamble = preamble[: _PREAMBLE_HARD_CAP] + "\n[context truncated]\n\n"
    return preamble


def extract_image_blocks(context: MessageContext | None) -> list[dict]:
    """Turn 'image' attachments into Claude image content blocks.

    Each image attachment carries a data URL string ("data:image/png;base64,…")
    in its `data` field. We parse it into the {"type":"image","source":{…}}
    block the stream-json user message expects. Non-image / malformed
    attachments are skipped.
    """
    if not context:
        return []
    blocks: list[dict] = []
    for att in context.attachments:
        if att.kind != "image":
            continue
        block = _data_url_to_image_block(att.data)
        if block:
            blocks.append(block)
    return blocks


def _data_url_to_image_block(data: object) -> dict | None:
    """Parse a base64 data URL into a Claude image content block, or None."""
    if not isinstance(data, str) or not data.startswith("data:"):
        return None
    try:
        header, b64 = data.split(",", 1)
    except ValueError:
        return None
    if not b64:
        return None
    media_type = header[len("data:"):].split(";", 1)[0] or "image/png"
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": b64},
    }


def _summarise_attachment_data(kind: str, data: object) -> str:
    if kind == "screenshot":
        if isinstance(data, dict):
            url = data.get("url", "")
            note = data.get("note", "")
            return f" screenshot_url={url!r} note={note!r}"
        return ""
    if kind == "console":
        lines: list[str] = []
        if isinstance(data, list):
            for entry in data[:10]:
                if isinstance(entry, dict):
                    level = entry.get("level", "")
                    msg = str(entry.get("message", ""))[:120]
                    lines.append(f"{level}: {msg}")
                else:
                    lines.append(str(entry)[:120])
        return f" console_errors=[{'; '.join(lines)}]"
    if kind == "snapshot":
        if isinstance(data, list):
            items = [
                f"{e.get('role','?')}:{e.get('name','?')}" if isinstance(e, dict) else str(e)
                for e in data[:15]
            ]
            return f" elements=[{', '.join(items)}]"
    if isinstance(data, str):
        return f" data={data[:200]!r}"
    return ""
