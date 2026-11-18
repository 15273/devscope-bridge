"""Verified task loop: run a sequence of browser steps and check each one.

This is the first autonomy gap from docs/roadmap.md. Leading computer-use
agents don't just fire clicks — they observe, act, and verify, retrying when
the page didn't end up in the expected state. DevScope already has snapshots
and a tool surface; this loop composes them.

A step is ``{tool, args, verify?}``. *verify* may include:
- ``text`` / ``selector`` — delegated to ``browser_assert_text``
- ``url_includes`` — the current tab URL must contain this substring
- ``selector_exists`` — ``browser_wait_for_selector``
- ``console_not_contains`` — recent console text must not include this

Steps never include submit / auto-apply actions. The loop refuses tools whose
names suggest a form submission.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Iterable

FORBIDDEN_TOOLS = frozenset({
    "browser_submit",
    "browser_click_submit",
    "submit",
})
FORBIDDEN_SELECTOR_HINTS = ("[type=submit]", "button[type='submit']", "input[type=submit]")

DispatchFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def is_forbidden_step(tool: str, args: dict[str, Any] | None = None) -> bool:
    name = (tool or "").strip().lower()
    if name in FORBIDDEN_TOOLS or name.endswith("_submit") or "auto_apply" in name:
        return True
    selector = str((args or {}).get("selector") or "").lower().replace('"', "'")
    if "submit" in name and "assert" not in name:
        return True
    for hint in FORBIDDEN_SELECTOR_HINTS:
        if hint in selector:
            return True
    return False


async def _verify(
    dispatch: DispatchFn,
    verify: dict[str, Any],
    tab_args: dict[str, Any],
) -> tuple[bool, str]:
    if not verify:
        return True, "no verify clause"
    if text := verify.get("text"):
        args = {**tab_args, "text": text}
        if verify.get("selector"):
            args["selector"] = verify["selector"]
        result = await dispatch("browser_assert_text", args)
        if not result.get("ok"):
            return False, result.get("error") or "assert_text failed"
        data = result.get("data") or {}
        if isinstance(data, dict) and data.get("present") is False:
            return False, "assert_text: text not present"
    if sel := verify.get("selector_exists") or (verify.get("selector") if "text" not in verify else None):
        result = await dispatch(
            "browser_wait_for_selector",
            {**tab_args, "selector": sel, "timeout_ms": int(verify.get("timeout_ms") or 3000)},
        )
        if not result.get("ok"):
            return False, result.get("error") or f"selector not found: {sel}"
    if needle := verify.get("url_includes"):
        result = await dispatch("browser_get_page_info", tab_args)
        url = ""
        if result.get("ok"):
            url = str((result.get("data") or {}).get("url") or "")
        if needle not in url:
            return False, f"url {url!r} does not include {needle!r}"
    if banned := verify.get("console_not_contains"):
        result = await dispatch("browser_get_console", {**tab_args, "max": 100})
        entries = ((result.get("data") or {}).get("entries") or []) if result.get("ok") else []
        blob = " ".join(str(e.get("text") or "") for e in entries if isinstance(e, dict))
        if banned in blob:
            return False, f"console contained {banned!r}"
    return True, "ok"


async def run_verified_steps(
    steps: Iterable[dict[str, Any]],
    dispatch: DispatchFn,
    *,
    max_retries: int = 2,
    tab_id: int | str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Run *steps* in order, verifying and retrying each one.

    *dispatch(tool, args)* must perform one browser action and return
    ``{ok, data, error}``. The loop does not call an LLM; the caller (or an
    agent) supplies the plan.
    """
    tab_args: dict[str, Any] = {}
    if tab_id not in (None, ""):
        tab_args["tab_id"] = tab_id
    if profile:
        tab_args["profile"] = profile

    history: list[dict[str, Any]] = []
    step_list = list(steps or [])
    if not step_list:
        return {"ok": False, "error": "steps is required", "completed": 0, "history": []}

    for index, raw in enumerate(step_list):
        if not isinstance(raw, dict):
            return {"ok": False, "error": f"step {index} is not an object", "completed": index, "history": history}
        tool = str(raw.get("tool") or "")
        args = dict(raw.get("args") or {})
        verify = dict(raw.get("verify") or {})
        if not tool:
            return {"ok": False, "error": f"step {index} is missing tool", "completed": index, "history": history}
        if is_forbidden_step(tool, args):
            return {
                "ok": False,
                "error": f"step {index} refused: {tool} looks like a submit/auto-apply action",
                "completed": index,
                "history": history,
            }
        merged = {**tab_args, **args}
        last_error = ""
        success = False
        attempts = 0
        for attempt in range(max(1, int(max_retries) + 1)):
            attempts = attempt + 1
            result = await dispatch(tool, merged)
            if not result.get("ok"):
                last_error = result.get("error") or f"{tool} failed"
                history.append({"step": index, "attempt": attempts, "tool": tool, "ok": False, "error": last_error})
                continue
            verified, reason = await _verify(dispatch, verify, tab_args)
            history.append({
                "step": index,
                "attempt": attempts,
                "tool": tool,
                "ok": verified,
                "error": None if verified else reason,
            })
            if verified:
                success = True
                break
            last_error = reason
        if not success:
            return {
                "ok": False,
                "error": f"step {index} ({tool}) failed after {attempts} attempt(s): {last_error}",
                "completed": index,
                "history": history,
            }
    return {"ok": True, "error": None, "completed": len(step_list), "history": history}
