"""T3：任务信封 / 三个适配器 / 路由的一致性测试。"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from geo_harness.agents.adapters import HTTPAgentAdapter, MCPAgentAdapter, SDKAgentAdapter
from geo_harness.agents.protocol import AgentCapabilities, TaskEnvelope
from geo_harness.agents.router import Router
from tests.agents.conformance import check_adapter, envelope


def test_envelope_accepts_minimal_and_full_forms():
    minimal = TaskEnvelope(task_id="t", thread_id="th", goal="查数据")
    assert minimal.budget.tier == "medium" and minimal.constraints.must_confirm
    full = envelope(context={"page": "workbench", "selection": {"ids": ["a"]}, "case_id": "c"})
    assert full.context.page == "workbench" and full.context.selection["ids"] == ["a"]


def test_envelope_rejects_missing_fields_and_unknown_keys():
    with pytest.raises(ValidationError):
        TaskEnvelope(task_id="t", thread_id="th")
    with pytest.raises(ValidationError):
        envelope(extra_field=1)
    with pytest.raises(ValidationError):
        envelope(budget={"tier": "huge"})


@pytest.mark.parametrize("adapter", [HTTPAgentAdapter("http://127.0.0.1:1"), MCPAgentAdapter(), SDKAgentAdapter()])
def test_adapters_are_honest_about_being_unconfigured(adapter):
    asyncio.run(check_adapter(adapter))


def test_adapter_keeps_transport_and_name():
    adapter = HTTPAgentAdapter("http://127.0.0.1:1", name="eo")
    assert adapter.transport == "http" and adapter.name == "eo"


def test_router_prefers_explicit_mention():
    router = Router({"main": AgentCapabilities(name="main"), "eo": AgentCapabilities(name="eo")})
    decision = router.route(envelope(goal="帮我看一下这个"), mention="eo")
    assert decision.agent == "eo" and decision.confidence == 1.0


def test_router_matches_keywords_per_subsystem():
    router = Router(
        {
            "main": AgentCapabilities(name="main"),
            "eo": AgentCapabilities(name="eo"),
            "assessment": AgentCapabilities(name="assessment"),
            "learning": AgentCapabilities(name="learning"),
        }
    )
    assert router.route(envelope(goal="用 Sentinel 影像做变化检测")).agent == "eo"
    assert router.route(envelope(goal="生成 SDG 指标评估报告")).agent == "assessment"
    assert router.route(envelope(goal="有哪些课程可以学习")).agent == "learning"


def test_router_uses_classifier_above_threshold_and_falls_back_otherwise():
    router = Router({"main": AgentCapabilities(name="main"), "eo": AgentCapabilities(name="eo")},
                    classifier=lambda goal: ("eo", 0.9))
    assert router.route(envelope(goal="分析一下")).agent == "eo"

    weak = Router({"main": AgentCapabilities(name="main"), "eo": AgentCapabilities(name="eo")},
                  classifier=lambda goal: ("eo", 0.2))
    assert weak.route(envelope(goal="分析一下")).agent == "main"

    silent = Router({"main": AgentCapabilities(name="main")})
    decision = silent.route(envelope(goal="分析一下"))
    assert decision.agent == "main" and "默认" in decision.reason


def test_routing_is_off_by_default(monkeypatch):
    from geo_harness.agents.router import routing_enabled

    monkeypatch.delenv("GEONEXUS_AGENT_ROUTING", raising=False)
    assert routing_enabled() is False
    monkeypatch.setenv("GEONEXUS_AGENT_ROUTING", "on")
    assert routing_enabled() is True
