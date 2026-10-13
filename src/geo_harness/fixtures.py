"""Generate redistributable synthetic fixtures; no real wetland claims."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from .core import file_digest

DEMO_ID = "org.geonexus.synthetic-wetland"
MAP_ID = "org.geonexus.geolibre"
RECIPE_ID = "recipe://geonexus/synthetic-wetland@0.1.0"


def seed_market(market: Path) -> None:
    seed_viewer(market)
    demo = market / "synthetic-wetland"
    if (demo / "manifest.json").exists():
        return
    demo.mkdir(parents=True, exist_ok=True)

    def save(name, value):
        path = demo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    rng = random.Random(42)
    training = [(rng.uniform(-0.5, 0.9), 0) for _ in range(160)]
    training = [(x, int(x > 0.25 + rng.uniform(-0.08, 0.08))) for x, _ in training]
    intercept = weight = 0.0
    for _ in range(1500):
        probs = [1 / (1 + math.exp(-(intercept + weight * x))) for x, _ in training]
        intercept -= (
            0.25 * sum(p - y for p, (_, y) in zip(probs, training, strict=True)) / len(training)
        )
        weight -= (
            0.25
            * sum((p - y) * x for p, (x, y) in zip(probs, training, strict=True))
            / len(training)
        )
    save(
        "model/weights.json",
        {
            "kind": "logistic-regression",
            "intercept": intercept,
            "weight": weight,
            "training_seed": 42,
            "training_samples": 160,
        },
    )
    features = []
    for row in range(8):
        for col in range(12):
            red = 0.1 + rng.random() * 0.6
            nir = 0.1 + rng.random() * 0.8
            features.append(
                {
                    "type": "Feature",
                    "id": row * 12 + col,
                    "geometry": {
                        "type": "Point",
                        "coordinates": [120.0 + col * 0.035, 30.0 + row * 0.035],
                    },
                    "properties": {
                        "red": round(red, 6),
                        "nir": round(nir, 6),
                        "synthetic": True,
                    },
                }
            )
    save("data/chip.geojson", {"type": "FeatureCollection", "features": features})
    common = {
        "geocard_version": "1.0",
        "license": "CC0-1.0",
        "provenance": {"provider": "GeoNexus synthetic fixture"},
        "compliance": {"sensitivity": "public"},
    }
    items = [
        (
            "data",
            "fixture.data",
            "合成多波段样例",
            {
                "spatial": {"crs": "EPSG:4326", "bbox": [120, 30, 120.385, 30.245]},
                "access": {
                    "protocol": "artifact",
                    "endpoint": "package://data/chip.geojson",
                },
                "x-geonexus": {
                    "profile": "data/1",
                    "revision": "0.1.0",
                    "artifact": {"digest": file_digest(demo / "data/chip.geojson")},
                },
            },
        ),
        (
            "skill",
            "fixture.ndvi",
            "NDVI 特征算子",
            {
                "access": {"protocol": "mcp", "endpoint": "service://fixture-node"},
                "x-geonexus": {
                    "profile": "operator/1",
                    "revision": "0.1.0",
                    "input_schema": {"type": "object", "properties": {}},
                    "output_schema": {"type": "object", "required": ["features_ref"]},
                    "tool": "ndvi_features",
                },
            },
        ),
        (
            "model",
            "fixture.logistic",
            "演示逻辑回归分类模型",
            {
                "access": {"protocol": "fixture", "endpoint": "service://fixture-node"},
                "runtime": {"cpu": 1, "memory": "16Mi", "gpu": "none"},
                "inputs": [{"name": "features_ref", "type": "string", "required": True}],
                "outputs": [{"name": "classification_ref", "type": "string"}],
                "x-geonexus": {
                    "profile": "model/1",
                    "revision": "0.1.0",
                    "model_id": "fixture.logistic",
                    "artifact": {"digest": file_digest(demo / "model/weights.json")},
                    "input_schema": {
                        "type": "object",
                        "required": ["features_ref"],
                        "properties": {"features_ref": {"type": "string"}},
                    },
                    "output_schema": {
                        "type": "object",
                        "required": ["classification_ref", "summary"],
                    },
                },
            },
        ),
        (
            "compute",
            "fixture.compute",
            "本地演示算力",
            {
                "access": {"protocol": "mcp", "endpoint": "service://fixture-node"},
                "runtime": {"cpu": 1, "memory": "256Mi", "gpu": "none"},
                "x-geonexus": {
                    "profile": "compute/1",
                    "revision": "0.1.0",
                    "backends": ["fixture-logistic", "python"],
                },
            },
        ),
    ]
    for kind, card_id, name, sections in items:
        save(
            f"cards/{kind}.json",
            {
                **common,
                "id": card_id,
                "type": kind,
                "name": name,
                "description": "固定合成数据与方法，仅验证技术链路，不代表真实生态研究结果。",
                **sections,
            },
        )
    recipe = {
        "recipe_version": "1.0",
        "id": RECIPE_ID,
        "name": "合成样例分类与地图交付",
        "params": [
            {
                "name": "threshold",
                "type": "number",
                "default": 0.6,
                "minimum": 0,
                "maximum": 1,
                "target": "classify.params.threshold",
            }
        ],
        "steps": [
            {
                "id": "features",
                "kind": "skill",
                "uses": "fixture.ndvi",
                "outputs": {"features_ref": "artifact://fixture/features"},
            },
            {
                "id": "classify",
                "kind": "model",
                "uses": "fixture.logistic",
                "depends_on": ["features"],
                "inputs": {"features_ref": "step://features/features_ref"},
                "params": {"threshold": "${params.threshold}"},
                "outputs": {
                    "classification_ref": "artifact://fixture/classification",
                    "summary": "artifact://fixture/summary",
                },
            },
        ],
        "requires": [
            "fixture.data",
            "fixture.ndvi",
            "fixture.logistic",
            "fixture.compute",
        ],
        "outputs": [
            {
                "name": "classification",
                "from": "classify.classification_ref",
                "role": "data",
            },
            {"name": "summary", "from": "classify.summary", "role": "knowledge"},
        ],
        "data_snapshot": {"fixture": "0.1.0"},
        "license": "CC0-1.0",
    }
    save("recipe.json", recipe)
    save(
        "cards/case.json",
        {
            **common,
            "id": "fixture.case",
            "type": "workflow",
            "name": "通用四类资源完整案例",
            "description": "安装固定版本后运行特征计算、模型分类和地图交付；合成数据演示。",
            "composition": {"components": [{"id": item[1], "role": item[0]} for item in items]},
            "params": {"params": recipe["params"]},
            "recipe_ref": {"recipe_id": RECIPE_ID, "version": "0.1.0"},
        },
    )
    skill = demo / "skills/wetland/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: synthetic-wetland\ndescription: Run the synthetic four-resource demo and explain its limits.\n---\nUse product_search and case_plan first. Execute only after the host has granted permission. Report that the data and model are synthetic. Preserve the package lock and input/model digests.\n"
    )
    manifest = {
        "manifest_version": "0.1",
        "id": DEMO_ID,
        "version": "0.1.0",
        "name": "四类资源 · 合成分类案例",
        "description": "数据 → NDVI 算子 → 小型模型 → 本地算力 → 可视化。无需 LLM 或外部账号。",
        "kind": "case",
        "permissions": ["workspace:artifacts", "fixture:execute"],
        "cards": [f"cards/{item[0]}.json" for item in items] + ["cards/case.json"],
        "skills": ["skills/wetland/SKILL.md"],
        "recipe": "recipe.json",
        "runtime": "fixture-node",
        "dependencies": [],
        "license": "CC0-1.0",
    }
    manifest["files"] = {
        str(p.relative_to(demo)): file_digest(p) for p in sorted(demo.rglob("*")) if p.is_file()
    }
    save("manifest.json", manifest)


def seed_viewer(market: Path) -> None:
    viewer = market / "geolibre"
    if (viewer / "manifest.json").exists():
        existing = json.loads((viewer / "manifest.json").read_text())
        if existing.get("version") not in {"0.1.0", "0.2.0"} or existing.get("id") != MAP_ID:
            return
        # Preserve custom edits. Existing installed 0.1 packages remain immutable.
        if existing.get("files", {}).get("SKILL.md") != file_digest(viewer / "SKILL.md"):
            return
    viewer.mkdir(parents=True, exist_ok=True)
    text = viewer / "SKILL.md"
    text.write_text(
        "---\nname: geolibre-viewer\ndescription: View verified GeoNode results with the official local GeoLibre app.\n---\nDefault viewer: the bundled opengeos/GeoLibre app at /viewer/. Use authenticated resource-results projects for real GeoJSON and GeoTIFF outputs. Preserve CRS, provenance, SHA256 and limitations. Never send private results to an external viewer. GeoLibre authoring uses the official Python project API or MCP tools. Desktop live relay is a separate capability.\n"
    )
    card = viewer / "card.json"
    card.write_text(
        json.dumps(
            {
                "geocard_version": "1.0",
                "id": MAP_ID,
                "type": "skill",
                "name": "GeoLibre 地图与三维地球",
                "description": "GeoHarness 默认地图查看器。使用 opengeos/GeoLibre 官方应用显示真实矢量与栅格结果，保留来源与坐标信息。",
                "license": "MIT",
                "tags": ["map", "viewer", "GeoLibre", "visualization"],
                "access": {"protocol": "application", "endpoint": "service://geoharness/viewer"},
                "provenance": {
                    "provider": "opengeos/GeoLibre",
                    "source": "https://github.com/opengeos/GeoLibre",
                    "lineage": "Official bundled viewer 3.3.0",
                },
                "compliance": {"sensitivity": "public"},
                "x-geonexus": {
                    "profile": "operator/1",
                    "revision": "0.2.1",
                    "tool": "view_result",
                    "source_url": "https://github.com/opengeos/GeoLibre",
                    "viewer_version": "3.3.0",
                    "input_schema": {
                        "type": "object",
                        "required": ["result_id"],
                        "properties": {"result_id": {"type": "string"}},
                    },
                    "output_schema": {"type": "object", "required": ["project_url", "viewer_url"]},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    (viewer / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": "0.1",
                "id": MAP_ID,
                "version": "0.2.1",
                "name": "GeoLibre 地图与三维地球",
                "description": "默认本机 GeoLibre 查看器，显示真实产品结果。官方 Viewer 与 authoring 依赖由客户端提供。",
                "kind": "viewer",
                "visibility": "public",
                "permissions": ["viewer:network", "workspace:artifacts"],
                "cards": ["card.json"],
                "skills": ["SKILL.md"],
                "dependencies": [],
                "files": {"SKILL.md": file_digest(text), "card.json": file_digest(card)},
                "license": "MIT",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
