"""Task envelope and adapter protocol shared by the main and subsystem agents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncIterator, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["lite", "medium", "heavy"]
Page = Literal["workbench", "map", "client"]


class AgentUnavailable(RuntimeError):
    """The subsystem agent cannot be reached or is not configured."""


class AgentTimeout(AgentUnavailable):
    """The subsystem agent did not answer within the envelope budget."""


class AgentRejected(AgentUnavailable):
    """The subsystem agent declined the task (policy, scope or capability)."""


class MapContextRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    page: Page = "workbench"
    map_revision: int | None = None
    selection: dict[str, Any] | None = None
    case_id: str | None = None


class Budget(BaseModel):
    tier: Tier = "medium"
    calls_left: int = Field(default=24, ge=0)


class Constraints(BaseModel):
    must_confirm: bool = True
    visibility: Literal["public", "restricted"] = "public"


class TaskEnvelope(BaseModel):
    """The only shape a subsystem agent has to understand."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=80)
    thread_id: str = Field(min_length=1, max_length=80)
    parent_run_id: str | None = Field(default=None, max_length=80)
    goal: str = Field(min_length=1, max_length=4000)
    context: MapContextRef = Field(default_factory=MapContextRef)
    budget: Budget = Field(default_factory=Budget)
    constraints: Constraints = Field(default_factory=Constraints)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentCapabilities(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=80)
    domains: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    budget_hint: Tier = "medium"


class RouteDecision(BaseModel):
    agent: str
    confidence: float = Field(ge=0, le=1)
    reason: str


class AgentAdapter(Protocol):
    """Every subsystem adapter implements exactly these four methods."""

    name: str

    async def health(self) -> dict[str, Any]: ...

    async def capabilities(self) -> AgentCapabilities: ...

    def task(self, envelope: TaskEnvelope) -> AsyncIterator[dict[str, Any]]: ...

    async def cancel(self, task_id: str) -> None: ...
