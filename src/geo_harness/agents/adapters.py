"""Three transport placeholders for subsystem agents (not wired yet).

They exist so the router and the conformance suite can be developed and tested
before the subsystems settle on HTTP, MCP or a private SDK. Each method states
clearly that it is unconfigured instead of pretending to work.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from .protocol import AgentCapabilities, AgentUnavailable, TaskEnvelope

DETAIL = "子系统接口尚未确定：适配器未接线（HTTP/MCP/SDK 三选一，待接口确认后填充）"


class _Unconfigured:
    name = "unconfigured"
    transport = "none"

    def __init__(self, endpoint: str | None = None, *, name: str | None = None) -> None:
        self.endpoint = endpoint
        if name:
            self.name = name

    async def health(self) -> dict[str, Any]:
        return {"status": "unsupported", "transport": self.transport, "detail": DETAIL}

    async def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(name=self.name, domains=[], skills=[])

    async def task(self, envelope: TaskEnvelope) -> AsyncIterator[dict[str, Any]]:
        raise AgentUnavailable(DETAIL)
        yield {}  # pragma: no cover - keeps this an async generator

    async def cancel(self, task_id: str) -> None:
        return None


class HTTPAgentAdapter(_Unconfigured):
    transport = "http"


class MCPAgentAdapter(_Unconfigured):
    transport = "mcp"


class SDKAgentAdapter(_Unconfigured):
    transport = "sdk"
