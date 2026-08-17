"""turn_id registry + stderr drain wiring."""
import pytest

from devscope_bridge import session_reader


def test_turn_id_registry_roundtrip():
    session_reader.set_current_turn_id("s1", "abc123")
    assert session_reader.get_current_turn_id("s1") == "abc123"
    session_reader.set_current_turn_id("s1", None)
    assert session_reader.get_current_turn_id("s1") is None


def test_turn_id_registry_isolated_per_session():
    session_reader.set_current_turn_id("a", "t-a")
    session_reader.set_current_turn_id("b", "t-b")
    assert session_reader.get_current_turn_id("a") == "t-a"
    assert session_reader.get_current_turn_id("b") == "t-b"


@pytest.mark.asyncio
async def test_drain_stderr_consumes_lines_without_raising():
    from devscope_bridge.session_manager import _drain_stderr

    class FakeStderr:
        def __init__(self, lines): self._lines = lines
        def __aiter__(self): return self
        async def __anext__(self):
            if not self._lines: raise StopAsyncIteration
            return self._lines.pop(0)

    class FakeProc:
        stderr = FakeStderr([b"warning: x\n", b"\n", b"boom\n"])

    await _drain_stderr("s", FakeProc())


def test_stderr_tail_empty_when_untouched():
    assert session_reader.get_stderr_tail("never-touched-session") == ""


@pytest.mark.asyncio
async def test_drain_stderr_feeds_crash_diagnostics_tail():
    """_drain_stderr must be the sole consumer of proc.stderr AND retain the
    tail: continuous_reader's process-exit path reads session_reader
    .get_stderr_tail(name) instead of proc.stderr.read() (single-consumer
    StreamReader would otherwise return b"" or raise after drain runs), so
    AiError.stderr_tail must still surface real crash diagnostics.
    """
    from devscope_bridge.session_manager import _drain_stderr

    class FakeStderr:
        def __init__(self, lines): self._lines = lines
        def __aiter__(self): return self
        async def __anext__(self):
            if not self._lines: raise StopAsyncIteration
            return self._lines.pop(0)

    class FakeProc:
        stderr = FakeStderr([b"Error: something failed\n", b"at line 42\n"])

    await _drain_stderr("crash-diag-test", FakeProc())

    tail = session_reader.get_stderr_tail("crash-diag-test")
    assert tail  # non-empty — this is what AiError.stderr_tail would carry
    assert "at line 42" in tail
    assert "Error: something failed" in tail


@pytest.mark.asyncio
async def test_drain_stderr_never_raises_on_mid_iteration_error():
    from devscope_bridge.session_manager import _drain_stderr

    class RaisingStderr:
        def __init__(self, lines): self._lines = lines
        def __aiter__(self): return self
        async def __anext__(self):
            if not self._lines: raise StopAsyncIteration
            item = self._lines.pop(0)
            if item == b"__RAISE__":
                raise RuntimeError("boom mid-iteration")
            return item

    class FakeProc:
        stderr = RaisingStderr([b"before crash\n", b"__RAISE__", b"never reached\n"])

    # Must not raise — drain is fire-and-forget and must never take the caller down.
    await _drain_stderr("raise-mid-iter", FakeProc())

    # Lines seen before the mid-iteration exception are still preserved.
    tail = session_reader.get_stderr_tail("raise-mid-iter")
    assert "before crash" in tail
