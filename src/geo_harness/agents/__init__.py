"""Subsystem agent contracts (T3): envelope, adapters, router.

Nothing here is wired into the conversation loop yet. The adapters are
deliberately unconfigured placeholders until each subsystem provides its task
interface; the router can be exercised on its own.
"""

from .protocol import (
    AgentCapabilities,
    AgentUnavailable,
    RouteDecision,
    TaskEnvelope,
)
from .router import Router

__all__ = ["AgentCapabilities", "AgentUnavailable", "RouteDecision", "TaskEnvelope", "Router"]
