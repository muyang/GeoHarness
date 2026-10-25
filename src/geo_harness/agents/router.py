"""Rule-first routing between the main agent and the subsystem agents.

Order: explicit mention → page hint + keywords → optional LLM classifier →
main agent fallback. The classifier is injected (a callable returning
``(agent, confidence)``); no model call happens here, so routing stays testable
and cost-free until a subsystem is actually connected.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

from .protocol import AgentCapabilities, RouteDecision, TaskEnvelope

KEYWORDS: dict[str, tuple[str, ...]] = {
    "eo": ("卫星", "影像", "遥感", "变化检测", "观测", "sentinel", "landsat", "sar"),
    "assessment": ("指标", "sdg", "评估", "情景", "报告", "可持续", "脆弱性"),
    "learning": ("课程", "教学", "学习", "培训", "课件", "教学案例"),
}
MENTION = re.compile(r"@([A-Za-z0-9_.-]{2,40})")


class Router:
    def __init__(
        self,
        agents: dict[str, AgentCapabilities] | None = None,
        default: str = "main",
        classifier: Callable[[str], tuple[str, float]] | None = None,
    ) -> None:
        self.agents = agents or {}
        self.default = default
        self.classifier = classifier

    def route(self, envelope: TaskEnvelope, mention: str | None = None) -> RouteDecision:
        for name in self.agents:
            if mention and mention == name:
                return RouteDecision(agent=name, confidence=1.0, reason="显式指定")

        mentioned = MENTION.search(envelope.goal)
        if mentioned:
            candidate = mentioned.group(1)
            if candidate in self.agents:
                return RouteDecision(agent=candidate, confidence=1.0, reason="目标中 @提及")

        lowered = envelope.goal.lower()
        best: tuple[str, int] | None = None
        for name, words in KEYWORDS.items():
            if name not in self.agents:
                continue
            hits = sum(1 for word in words if word in lowered)
            if hits and (best is None or hits > best[1]):
                best = (name, hits)
        if best is not None:
            confidence = min(0.6 + 0.1 * best[1], 0.9)
            return RouteDecision(agent=best[0], confidence=confidence, reason=f"关键词命中 {best[0]}（{best[1]} 处）")

        if self.classifier is not None:
            try:
                agent, confidence = self.classifier(envelope.goal)
            except Exception:  # pragma: no cover - classifier is optional
                agent, confidence = self.default, 0.0
            if agent in self.agents and confidence >= 0.6:
                return RouteDecision(agent=agent, confidence=confidence, reason="模型分类")

        return RouteDecision(agent=self.default, confidence=0.4, reason="默认路由（主智能体）")


def routing_enabled() -> bool:
    """Routing stays off until a subsystem adapter is actually configured."""
    return os.environ.get("GEONEXUS_AGENT_ROUTING", "").strip().lower() in {"1", "true", "yes", "on"}
