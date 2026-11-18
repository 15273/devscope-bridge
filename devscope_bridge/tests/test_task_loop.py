import pytest

from devscope_bridge.task_loop import is_forbidden_step, run_verified_steps


def test_forbids_submit_tools_and_selectors():
    assert is_forbidden_step("browser_click_submit", {})
    assert is_forbidden_step("browser_click", {"selector": "button[type='submit']"})
    assert not is_forbidden_step("browser_click", {"selector": "button.autofill"})


@pytest.mark.asyncio
async def test_retries_until_verify_passes():
    calls = []

    async def dispatch(tool, args):
        calls.append((tool, args))
        if tool == "browser_click":
            return {"ok": True, "data": {"clicked": True}, "error": None}
        if tool == "browser_assert_text":
            # fail first verify, pass on retry
            present = sum(1 for t, _ in calls if t == "browser_assert_text") >= 2
            return {"ok": True, "data": {"present": present}, "error": None if present else "not yet"}
        raise AssertionError(tool)

    result = await run_verified_steps(
        [{"tool": "browser_click", "args": {"selector": "#go"}, "verify": {"text": "Done"}}],
        dispatch,
        max_retries=2,
        tab_id=7,
    )
    assert result["ok"] is True
    assert result["completed"] == 1
    assert any(t == "browser_click" and a.get("tab_id") == 7 for t, a in calls)


@pytest.mark.asyncio
async def test_refuses_submit_step():
    async def dispatch(tool, args):
        raise AssertionError("must not dispatch")

    result = await run_verified_steps(
        [{"tool": "browser_submit", "args": {}}],
        dispatch,
    )
    assert result["ok"] is False
    assert "refused" in result["error"]


@pytest.mark.asyncio
async def test_url_includes_verify():
    async def dispatch(tool, args):
        if tool == "browser_navigate":
            return {"ok": True, "data": {}, "error": None}
        if tool == "browser_get_page_info":
            return {"ok": True, "data": {"url": "https://jobs.lever.co/acme/apply"}, "error": None}
        raise AssertionError(tool)

    result = await run_verified_steps(
        [{"tool": "browser_navigate", "args": {"url": "https://jobs.lever.co/acme/apply"}, "verify": {"url_includes": "/apply"}}],
        dispatch,
    )
    assert result["ok"] is True
