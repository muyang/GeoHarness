"""T2：命令注册表（不启动工作台，用最小替身）。"""

from __future__ import annotations

import asyncio

import pytest
from geonexus.registration import RegistrationError

from geo_harness.commands import COMMANDS, CommandRegistry


class FakeWorkbench:
    def __init__(self, installed):
        self.installed = installed
        self.submitted = []

    def describe(self, product_id):
        if product_id not in self.installed:
            raise RegistrationError("未安装")
        return {"product_id": product_id, "digest": "sha:" + product_id, "tool": "x"}

    async def submit(self, product_id, arguments, digest, source="ui"):
        self.submitted.append({"product_id": product_id, "arguments": arguments, "digest": digest, "source": source})
        return {"id": "job-1"}


def test_list_marks_availability():
    registry = CommandRegistry(FakeWorkbench({COMMANDS["geom.buffer"]["product_id"]}))
    rows = {row["id"]: row for row in registry.list()}
    assert rows["geom.buffer"]["available"] is True
    assert rows["raster.zonal_stats"]["available"] is False


def test_execute_validates_required_arguments_and_delegates():
    wb = FakeWorkbench({COMMANDS["geom.buffer"]["product_id"]})
    registry = CommandRegistry(wb)
    with pytest.raises(RegistrationError):
        asyncio.run(registry.execute("geom.buffer", {}))
    job = asyncio.run(registry.execute("geom.buffer", {"distance": 500}, source="agent"))
    assert job["id"] == "job-1"
    assert wb.submitted[0]["source"] == "agent" and wb.submitted[0]["digest"] == "sha:" + COMMANDS["geom.buffer"]["product_id"]


def test_always_confirm_command_requires_policy_flag():
    wb = FakeWorkbench({COMMANDS["raster.zonal_stats"]["product_id"]})
    registry = CommandRegistry(wb)
    with pytest.raises(RegistrationError):
        asyncio.run(registry.execute("raster.zonal_stats", {"zones": "a"}))
    asyncio.run(registry.execute("raster.zonal_stats", {"zones": "a", "_policy_confirm": True}))
    assert wb.submitted


def test_unknown_command_and_uninstalled_product():
    registry = CommandRegistry(FakeWorkbench(set()))
    with pytest.raises(RegistrationError):
        registry.describe("geom.nope")
    with pytest.raises(RegistrationError):
        registry.describe("geom.buffer")
