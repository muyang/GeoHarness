"""Adapter conformance checks shared by tests (and, later, real adapters)."""

from __future__ import annotations

from geo_harness.agents.protocol import AgentUnavailable, TaskEnvelope


def envelope(**overrides) -> TaskEnvelope:
    data = {
        "task_id": "task-1",
        "thread_id": "thread-1",
        "goal": "识别某流域 2025 年水体变化",
        "context": {"page": "map", "map_revision": 7},
        "budget": {"tier": "medium", "calls_left": 24},
    }
    data.update(overrides)
    return TaskEnvelope(**data)


async def check_adapter(adapter) -> None:
    health = await adapter.health()
    assert health["status"] == "unsupported" and health["detail"], health

    capabilities = await adapter.capabilities()
    assert capabilities.name and isinstance(capabilities.skills, list)

    try:
        async for _ in adapter.task(envelope()):
            raise AssertionError("unconfigured adapter must not yield events")
    except AgentUnavailable as error:
        assert "未接线" in str(error)

    await adapter.cancel("task-1")  # cancellation is idempotent and never raises
