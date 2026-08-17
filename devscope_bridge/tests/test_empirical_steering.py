"""
test_empirical_steering.py — EMPIRICAL RESEARCH TEST (run manually, not in CI).

Spawns a REAL claude process and sends two messages, the second mid-turn,
then records observations about:
  - Whether the 2nd message interrupts or queues
  - How many result events appear
  - Whether a new system/init fires for the 2nd message

Mark: @pytest.mark.empirical (excluded from CI via -m "not empirical")
Run: pytest devscope_bridge/tests/test_empirical_steering.py -v -s -m empirical
"""

import asyncio
import json
import time
import pytest


def encode_msg(text: str) -> bytes:
    payload = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


@pytest.mark.asyncio
@pytest.mark.empirical
async def test_mid_turn_steering_empirically(capsys):
    """Spawn real claude, send msg2 mid-turn, record what happens."""
    args = [
        "claude",
        "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
    ]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    observations: list[dict] = []
    t0 = time.time()

    async def reader():
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                observations.append({"type": "non_json", "raw": line[:80], "t": time.time() - t0})
                continue
            ev_type = ev.get("type", "?")
            ev_sub = ev.get("subtype", "")
            obs = {"type": ev_type, "sub": ev_sub, "t": round(time.time() - t0, 2)}
            if ev_type == "result":
                obs["is_error"] = ev.get("is_error")
                obs["result_preview"] = str(ev.get("result", ""))[:80]
            elif ev_type == "system" and ev_sub == "init":
                obs["session_id"] = ev.get("session_id", "")
            elif ev_type == "stream_event":
                delta = ev.get("event", {}).get("delta", {})
                if delta.get("type") == "text_delta":
                    obs["text_preview"] = delta.get("text", "")[:20]
                    observations.append(obs)
                # skip non-text stream events entirely
                continue
            observations.append(obs)

    reader_task = asyncio.create_task(reader())

    # Msg1: a turn that takes ~3-5 seconds
    msg1 = "Count from 1 to 15. Write each number on its own line. Take your time."
    print(f"\n[t=0.00] SEND MSG1: {msg1!r}", flush=True)
    assert proc.stdin
    proc.stdin.write(encode_msg(msg1))
    await proc.stdin.drain()

    # Wait 2.5s — enough for streaming to start but not finish
    await asyncio.sleep(2.5)

    msg2 = "STOP. Just respond with the single word: STEERED"
    print(f"\n[t={time.time()-t0:.2f}] SEND MSG2 (mid-turn): {msg2!r}", flush=True)
    proc.stdin.write(encode_msg(msg2))
    await proc.stdin.drain()

    # Wait for completion — up to 40s total
    await asyncio.sleep(35)

    reader_task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(reader_task), 1)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), 3)
    except asyncio.TimeoutError:
        proc.kill()

    assert proc.stderr
    stderr_bytes = await proc.stderr.read()
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    if stderr_text.strip():
        print(f"\n[STDERR tail 500]\n{stderr_text[-500:]}")

    # ── Analyse observations ──────────────────────────────────────────────

    result_events = [o for o in observations if o["type"] == "result"]
    init_events = [o for o in observations if o["type"] == "system" and o.get("sub") == "init"]
    chunks = [o for o in observations if o.get("text_preview") is not None]

    print("\n\n=== EMPIRICAL FINDINGS ===")
    print(f"Total observations: {len(observations)}")
    print(f"Init events: {len(init_events)}")
    print(f"Chunk events: {len(chunks)}")
    print(f"Result events: {len(result_events)}")
    for r in result_events:
        print(f"  result at t={r['t']}s: is_error={r.get('is_error')} preview={r.get('result_preview','')!r}")
    if chunks:
        print(f"  first chunk at t={chunks[0]['t']}s: {chunks[0].get('text_preview','')!r}")
        print(f"  last  chunk at t={chunks[-1]['t']}s: {chunks[-1].get('text_preview','')!r}")
    print("=== END FINDINGS ===\n")

    # Assertions that record the empirical truth
    assert len(result_events) >= 1, "Expected at least 1 result event (one per completed turn)"

    # The test PASSES regardless of count — it's empirical research.
    # The count is printed so we can record the finding.
    print(f"\nKEY FINDING: {len(result_events)} result event(s) for 2 messages sent.")
    if len(result_events) == 1:
        print("INTERPRETATION: 2nd message was QUEUED — processed as a 2nd turn after 1st completed.")
        print("  Both turns = single continuous stdout, 1 result per turn.")
    elif len(result_events) == 2:
        print("INTERPRETATION: 2 separate result events — each message got its own turn.")
    else:
        print(f"INTERPRETATION: Unexpected {len(result_events)} results.")

    if len(init_events) == 1:
        print("INIT: Only 1 system/init — 2nd turn reuses the same init (no new session).")
    elif len(init_events) == 2:
        print("INIT: 2 system/init events — one per turn.")
