#!/usr/bin/env python3
"""Load/soak check for the resumable workbench stream (run after SDK review).

Prerequisites: a running GeoHarness with a configured model (real chat), and a
local session (the script opens `/` and `/api/session` to obtain cookie + CSRF).

Examples:
    python scripts/load_stream.py --base http://127.0.0.1:8810 --requests 40 --concurrency 10
    python scripts/load_stream.py --base http://127.0.0.1:8810 --resume-check

It reports status codes, latency percentiles and (for --resume-check) whether the
resumed tail replays without duplicates or gaps.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid

import httpx


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * ratio))]


async def login(client: httpx.AsyncClient, base: str) -> str:
    """Open a local session and return its CSRF token."""
    await client.get(base + "/")
    session = await client.get(base + "/api/session")
    session.raise_for_status()
    return session.json().get("csrf", "")


async def one(client: httpx.AsyncClient, base: str, csrf: str, message: str, stream_id: str, resume_from: int | None = None) -> dict:
    headers = {"X-Geo-CSRF": csrf, "Content-Type": "application/json"}
    if resume_from is not None:
        headers["X-Resume-From"] = str(resume_from)
    started = time.perf_counter()
    status = 0
    events: list[dict] = []
    async with client.stream(
        "POST",
        base + "/api/workbench/chat/stream",
        json={"message": message, "stream_id": stream_id},
        headers=headers,
        timeout=120,
    ) as response:
        status = response.status_code
        if status == 200:
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return {"status": status, "seconds": time.perf_counter() - started, "events": events}


async def load(base: str, requests: int, concurrency: int) -> None:
    async with httpx.AsyncClient() as client:
        csrf = await login(client, base)
        gate = asyncio.Semaphore(concurrency)
        latencies: list[float] = []
        statuses: dict[int, int] = {}
        seq_gaps = 0

        async def task(index: int) -> None:
            nonlocal seq_gaps
            async with gate:
                result = await one(client, base, csrf, f"压测请求 {index}", uuid.uuid4().hex)
            statuses[result["status"]] = statuses.get(result["status"], 0) + 1
            if result["status"] == 200:
                latencies.append(result["seconds"])
                seqs = [event.get("seq") for event in result["events"] if "seq" in event]
                if seqs and seqs != list(range(1, len(seqs) + 1)):
                    seq_gaps += 1

        started = time.perf_counter()
        await asyncio.gather(*(task(i) for i in range(requests)))
        elapsed = time.perf_counter() - started

    print(json.dumps({
        "requests": requests,
        "concurrency": concurrency,
        "elapsed_s": round(elapsed, 2),
        "throughput_rps": round(requests / elapsed, 2),
        "statuses": statuses,
        "latency_p50": round(percentile(latencies, 0.50), 3),
        "latency_p95": round(percentile(latencies, 0.95), 3),
        "latency_p99": round(percentile(latencies, 0.99), 3),
        "sequence_gaps": seq_gaps,
    }, ensure_ascii=False, indent=2))


async def resume_check(base: str) -> None:
    async with httpx.AsyncClient() as client:
        csrf = await login(client, base)
        stream_id = uuid.uuid4().hex
        first = await one(client, base, csrf, "续传检查", stream_id)
        seqs = [event.get("seq") for event in first["events"] if "seq" in event]
        if not seqs:
            print(json.dumps({"ok": False, "reason": "no events", "status": first["status"]}, ensure_ascii=False))
            return
        tail = await one(client, base, csrf, "续传检查", stream_id, resume_from=seqs[0])
        tail_seqs = [event.get("seq") for event in tail["events"] if "seq" in event]
        ok = bool(tail_seqs) and min(tail_seqs) > seqs[0] and tail_seqs == sorted(set(tail_seqs)) and tail_seqs == list(range(seqs[0] + 1, seqs[0] + 1 + len(tail_seqs)))
        print(json.dumps({"ok": ok, "first_seqs": seqs[:5], "resumed_seqs": tail_seqs[:5], "statuses": [first["status"], tail["status"]]}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="GeoHarness stream load/soak check")
    parser.add_argument("--base", default="http://127.0.0.1:8810")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--resume-check", action="store_true")
    args = parser.parse_args()
    if args.resume_check:
        asyncio.run(resume_check(args.base))
    else:
        asyncio.run(load(args.base, args.requests, args.concurrency))


if __name__ == "__main__":
    main()
