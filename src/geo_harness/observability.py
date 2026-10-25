"""Production plumbing for the workbench stream: resumable events, idempotency,
a concurrency gate and in-process metrics. No I/O, no globals beyond instances."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, AsyncIterator, Awaitable, Callable


class EventLog:
    """Bounded, per-stream append-only log with sequence numbers."""

    def __init__(self, limit: int = 2000) -> None:
        self.limit = limit
        self.events: dict[str, deque[dict[str, Any]]] = {}
        self.next_seq: dict[str, int] = {}
        self.done: set[str] = set()

    def append(self, stream_id: str, event: dict[str, Any]) -> dict[str, Any]:
        seq = self.next_seq.get(stream_id, 0) + 1
        self.next_seq[stream_id] = seq
        record = {**event, "seq": seq}
        bucket = self.events.setdefault(stream_id, deque(maxlen=self.limit))
        bucket.append(record)
        return record

    def finish(self, stream_id: str) -> None:
        self.done.add(stream_id)

    def finished(self, stream_id: str) -> bool:
        return stream_id in self.done

    def replay(self, stream_id: str, from_seq: int = 0) -> list[dict[str, Any]]:
        return [event for event in self.events.get(stream_id, ()) if event["seq"] > from_seq]


class StreamHub:
    """Runs one generation task per stream and lets any number of readers follow it.

    A client that disconnects can reconnect with the last sequence it saw; it gets
    the buffered tail and then live events, without re-running the agent (which
    would duplicate side effects).
    """

    def __init__(self, log: EventLog | None = None) -> None:
        self.log = log or EventLog()
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.changed: dict[str, asyncio.Event] = {}

    def _notify(self, stream_id: str) -> None:
        event = self.changed.setdefault(stream_id, asyncio.Event())
        event.set()

    async def _run(self, stream_id: str, factory: Callable[[], AsyncIterator[dict[str, Any]]]) -> None:
        try:
            async for event in factory():
                self.log.append(stream_id, event)
                self._notify(stream_id)
        except Exception as error:  # keep the stream inspectable instead of losing it
            self.log.append(stream_id, {"type": "error", "error": str(error)[:500]})
        finally:
            self.log.finish(stream_id)
            self._notify(stream_id)

    def start(self, stream_id: str, factory: Callable[[], AsyncIterator[dict[str, Any]]]) -> None:
        if stream_id in self.tasks:
            return
        self.tasks[stream_id] = asyncio.create_task(self._run(stream_id, factory))

    async def follow(self, stream_id: str, from_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        cursor = from_seq
        while True:
            for event in self.log.replay(stream_id, cursor):
                cursor = event["seq"]
                yield event
            if self.log.finished(stream_id):
                return
            event = self.changed.setdefault(stream_id, asyncio.Event())
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat", "seq": cursor}

    async def close(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)


class IdempotencyStore:
    """Remember the first outcome of a key so a retried POST does not run twice."""

    def __init__(self, ttl: float = 900.0) -> None:
        self.ttl = ttl
        self.entries: dict[str, tuple[float, Any, bool]] = {}

    def get(self, key: str) -> tuple[bool, Any]:
        entry = self.entries.get(key)
        if not entry:
            return False, None
        created, value, pending = entry
        if time.monotonic() - created > self.ttl:
            self.entries.pop(key, None)
            return False, None
        return True, None if pending else value

    def begin(self, key: str) -> bool:
        """Return False when the key is already in flight or finished."""
        found, _ = self.get(key)
        if found:
            return False
        self.entries[key] = (time.monotonic(), None, True)
        return True

    def finish(self, key: str, value: Any) -> None:
        self.entries[key] = (time.monotonic(), value, False)

    def fail(self, key: str) -> None:
        self.entries.pop(key, None)


class ConcurrencyGate:
    """Bounded concurrency with immediate rejection (callers return 429)."""

    def __init__(self, limit: int = 8) -> None:
        self.limit = max(1, limit)
        self.active = 0
        self.peak = 0

    def acquire(self) -> bool:
        if self.active >= self.limit:
            return False
        self.active += 1
        self.peak = max(self.peak, self.active)
        return True

    def release(self) -> None:
        self.active = max(0, self.active - 1)

    def snapshot(self) -> dict[str, int]:
        return {"active": self.active, "limit": self.limit, "peak": self.peak}


class Metrics:
    """Counters and simple latency summaries (in-process, admin readable)."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.latencies: dict[str, deque[float]] = {}

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def observe(self, name: str, milliseconds: float) -> None:
        self.latencies.setdefault(name, deque(maxlen=512)).append(float(milliseconds))

    def snapshot(self) -> dict[str, Any]:
        result: dict[str, Any] = {"counters": dict(self.counters), "latencies": {}}
        for name, values in self.latencies.items():
            if not values:
                continue
            ordered = sorted(values)
            result["latencies"][name] = {
                "count": len(ordered),
                "p50": ordered[len(ordered) // 2],
                "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
                "max": ordered[-1],
            }
        return result
