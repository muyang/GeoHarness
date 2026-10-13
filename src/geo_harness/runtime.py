"""Client orchestration: all domain execution remains in the owning GeoNode."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geonexus.registration import RegistrationError
from mcp import StdioServerParameters

from .core import MCPConnection, Products, file_digest, read_json, write_private
from .fixtures import DEMO_ID, MAP_ID, RECIPE_ID


class Runtime:
    def __init__(self, workspace: Path, products: Products):
        self.workspace, self.products = workspace, products
        self.connections: dict[str, MCPConnection] = {}
        self.jobs: dict[str, asyncio.Task] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.node_key = secrets.token_urlsafe(32)
        for path in (workspace / "runs").glob("*/run.json"):
            record = read_json(path)
            if record["status"] in {"queued", "running", "cancel_requested"}:
                record.update(status="interrupted", error="客户端曾退出；可用相同参数重新运行。")
                write_private(path, record)
            self.runs[record["id"]] = record

    async def node(self) -> MCPConnection:
        package = self.products.active_path(DEMO_ID)
        if DEMO_ID not in self.connections:
            env = dict(os.environ)
            env["GEONEXUS_NODE_API_KEY"] = self.node_key
            # Explicit module path also supports running the source bundle before installation.
            env["PYTHONPATH"] = (
                str(Path(__file__).parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
            )
            server = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-m",
                    "geo_harness.demo_node",
                    "--package",
                    str(package),
                    "--artifacts",
                    str(self.workspace / "node-artifacts"),
                ],
                env=env,
            )
            self.connections[DEMO_ID] = MCPConnection(server)
        return self.connections[DEMO_ID]

    async def plan(self, params: dict[str, Any], run_id: str = "preview") -> dict[str, Any]:
        return await (await self.node()).tool(
            "geo_plan", {"recipe": RECIPE_ID, "params": params, "run_id": run_id}
        )

    async def start(self, params: dict[str, Any]) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        plan = await self.plan(params, run_id)
        record = {
            "id": run_id,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "params": plan["params"],
            "recipe": RECIPE_ID,
            "events": [],
            "product_lock": dict(self.products.installed[DEMO_ID]),
            "synthetic": True,
        }
        self.runs[run_id] = record
        self.persist(record)
        self.jobs[run_id] = asyncio.create_task(self.execute(record, plan))
        return record

    def persist(self, record: dict[str, Any]) -> None:
        write_private(self.workspace / "runs" / record["id"] / "run.json", record)

    async def execute(self, record: dict[str, Any], plan: dict[str, Any]) -> None:
        root = self.workspace / "runs" / record["id"]
        outputs: dict[str, dict[str, Any]] = {}
        try:
            record["status"] = "running"
            self.persist(record)
            node = await self.node()
            package = self.products.active_path(DEMO_ID)
            cards = {
                item["id"]: item
                for item in (read_json(path) for path in (package / "cards").glob("*.json"))
            }
            recipe_steps = {step["id"]: step for step in plan["recipe"]["steps"]}
            for task in plan["tasks"]:
                if record["status"] == "cancel_requested":
                    record["status"] = "cancelled_before_next_step"
                    self.persist(record)
                    return
                self.products.active_path(
                    DEMO_ID
                )  # Recheck grant and integrity at each execution boundary.
                step = recipe_steps[task["step"]]
                inputs = {}
                for name, ref in step.get("inputs", {}).items():
                    if not ref.startswith("step://"):
                        raise RegistrationError(
                            "This client executes only declared owned step references."
                        )
                    step_id, output_name = ref.removeprefix("step://").split("/", 1)
                    inputs[name] = outputs[step_id][output_name]
                record["events"].append({"step": task["step"], "state": "running"})
                self.persist(record)
                if task["kind"] == "skill":
                    tool = cards[task["declared_uses"]]["x-geonexus"]["tool"]
                    value = await node.tool(
                        "geo_execute",
                        {
                            "skill": tool,
                            "geocards": ["fixture.data", task["declared_uses"]],
                            "params": {**task["params"], **inputs},
                            "request_id": record["id"] + ":" + task["step"],
                        },
                    )
                elif task["kind"] == "model":
                    value = await node.tool(
                        "geo_invoke",
                        {
                            "model": task["declared_uses"],
                            "inputs": inputs,
                            "params": task["params"],
                            "timeout": 30,
                        },
                    )
                    if value.get("status") != "succeeded":
                        raise RegistrationError(value.get("error") or "Model invocation failed.")
                else:
                    raise RegistrationError(f"Unsupported execution kind: {task['kind']}")
                outputs[task["step"]] = value["outputs"]
                record["events"].append({"step": task["step"], "state": "completed"})
                self.persist(record)
            final = outputs["classify"]
            result = await node.tool(
                "geo_execute",
                {
                    "skill": "read_artifact",
                    "params": {"ref": final["classification_ref"]},
                },
            )
            geojson = result["outputs"]["content"]
            write_private(root / "classification.geojson", geojson)
            write_private(root / "summary.json", final["summary"])
            write_private(root / "plan.json", plan)
            manifest = read_json(package / "manifest.json")
            lock = {
                "recipe": RECIPE_ID,
                "params": plan["params"],
                "products": [record["product_lock"]],
                "input_and_model": {
                    key: value
                    for key, value in manifest["files"].items()
                    if key.startswith(("data/", "model/"))
                },
                "output_digest": file_digest(root / "classification.geojson"),
                "llm_required": False,
                "synthetic": True,
            }
            write_private(root / "lock.json", lock)
            record.update(
                summary=final["summary"],
                output_digest=lock["output_digest"],
                outputs=[
                    "classification.geojson",
                    "summary.json",
                    "plan.json",
                    "lock.json",
                ],
            )
            (root / "report.md").write_text(
                f"# 合成样例运行报告\n\n本结果仅用于验证技术链路，不代表真实湿地或鸟类研究。\n\n参数：`{json.dumps(plan['params'])}`\n\n产品：`{record['product_lock']['digest']}`\n\n结果：`{json.dumps(final['summary'], ensure_ascii=False)}`\n\n通过官方 MCP 调用 GeoNode；输入与模型留在执行节点，仅交付派生产物。\n"
            )
            record["outputs"].append("report.md")
            record["status"] = (
                "completed_after_cancel_request"
                if record["status"] == "cancel_requested"
                else "completed"
            )
        except Exception as exc:
            record.update(status="failed", error=str(exc)[:1200])
        finally:
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            self.persist(record)
            self.jobs.pop(record["id"], None)

    async def stop_product(self, product_id: str) -> None:
        if any(
            r["status"] in {"queued", "running", "cancel_requested"} for r in self.runs.values()
        ):
            raise RegistrationError(
                "Wait for the current run to stop before changing installed products."
            )
        connection = self.connections.pop(product_id, None)
        if connection:
            await connection.close()

    async def close(self) -> None:
        for record in self.runs.values():
            if record["status"] in {"queued", "running"}:
                record["status"] = "cancel_requested"
        if self.jobs:
            await asyncio.gather(*list(self.jobs.values()), return_exceptions=True)
        for connection in list(self.connections.values()):
            await connection.close()
        self.connections.clear()

    async def map_project(self, run_id: str, renderer: str = "maplibre") -> dict[str, Any]:
        self.products.active_path(MAP_ID)
        if renderer not in {"maplibre", "cesium"}:
            raise RegistrationError("Choose maplibre or cesium.")
        if run_id not in self.runs or "classification.geojson" not in self.runs[run_id].get(
            "outputs", []
        ):
            raise RegistrationError("A completed synthetic run is required.")
        try:
            import geolibre  # noqa: F401
        except ImportError as exc:
            raise RegistrationError(
                "Install the optional GeoLibre extra: pip install 'geoharness-client[geolibre]'."
            ) from exc
        root = self.workspace / "runs" / run_id
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "geolibre.mcp", "--root", str(root)],
            env=dict(os.environ),
        )
        conn = MCPConnection(server)
        try:
            tools = (await conn.request("list_tools")).tools
            schemas = {t.name: t.input_schema for t in tools}
            return await self._author_map(conn, schemas, root, renderer)
        finally:
            await conn.close()

    async def _author_map(self, conn, schemas, root, renderer):
        # Exact MCP arguments are validated against the installed GeoLibre tool contracts.
        from .core import validate_arguments

        project = f"classification-{renderer}.geolibre.json"
        calls = [
            (
                "create_project",
                {
                    "path": project,
                    "name": "GeoNexus 合成分类案例",
                    "center": [120.19, 30.12],
                    "zoom": 10,
                    "overwrite": True,
                },
            ),
            (
                "add_geojson_layer",
                {
                    "path": project,
                    "name": "合成分类结果",
                    "data": "classification.geojson",
                },
            ),
            (
                "classify_layer",
                {
                    "path": project,
                    "layer": "合成分类结果",
                    "column": "classification",
                    "class_count": 2,
                    "colormap": "viridis",
                },
            ),
            ("set_renderer", {"path": project, "renderer": renderer}),
        ]
        for tool, arguments in calls:
            if tool not in schemas:
                raise RegistrationError(f"GeoLibre version does not expose {tool}.")
            validate_arguments(schemas[tool], arguments)
            await conn.tool(tool, arguments)
        return {
            "file": project,
            "renderer": renderer,
            "project": read_json(root / project),
        }
