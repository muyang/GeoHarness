"""T5：可续传流 / 幂等 / 并发闸门 / 指标 的单元测试。"""

from __future__ import annotations

import asyncio

from geo_harness.observability import ConcurrencyGate, EventLog, IdempotencyStore, Metrics, StreamHub


def test_event_log_replays_after_sequence_and_is_bounded():
    log = EventLog(limit=3)
    for index in range(5):
        log.append("s", {"type": "token", "i": index})
    events = log.replay("s", 2)
    assert [e["seq"] for e in events] == [3, 4, 5]
    assert all(e["seq"] > 2 for e in events)


def test_stream_hub_follows_live_events_and_resumes_without_rerun():
    async def scenario():
        hub = StreamHub()
        produced = {"runs": 0}

        async def factory():
            produced["runs"] += 1
            for index in range(3):
                await asyncio.sleep(0)
                yield {"type": "token", "i": index}

        hub.start("s1", factory)
        first = [e async for e in hub.follow("s1")]
        assert [e["type"] for e in first] == ["token", "token", "token"]
        resumed = [e async for e in hub.follow("s1", from_seq=1)]
        assert [e["seq"] for e in resumed] == [2, 3]
        assert produced["runs"] == 1  # resume did not re-run the agent
        await hub.close()

    asyncio.run(scenario())


def test_stream_hub_records_errors_as_events():
    async def scenario():
        hub = StreamHub()

        async def factory():
            yield {"type": "token"}
            raise RuntimeError("boom")

        hub.start("s2", factory)
        events = [e async for e in hub.follow("s2")]
        assert events[-1]["type"] == "error" and "boom" in events[-1]["error"]
        await hub.close()

    asyncio.run(scenario())


def test_idempotency_store_rejects_duplicates_and_caches_result():
    store = IdempotencyStore()
    assert store.begin("k") is True
    assert store.begin("k") is False
    store.finish("k", {"plan": "p1"})
    assert store.get("k") == (True, {"plan": "p1"})
    store.fail("k2")
    assert store.get("k2") == (False, None)


def test_concurrency_gate_rejects_over_limit_and_tracks_peak():
    gate = ConcurrencyGate(limit=2)
    assert gate.acquire() and gate.acquire()
    assert gate.acquire() is False
    gate.release()
    assert gate.acquire() and gate.snapshot()["peak"] == 2


def test_metrics_snapshot_has_percentiles():
    metrics = Metrics()
    for value in (10, 20, 30, 40, 50):
        metrics.observe("stream", value)
    metrics.increment("streams")
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["streams"] == 1
    assert snapshot["latencies"]["stream"]["count"] == 5
    assert snapshot["latencies"]["stream"]["p50"] == 30
