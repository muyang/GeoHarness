"""Sovereign execution of the fixed fixture over the official MCP adapter."""

from __future__ import annotations

import argparse
import json
import math
import os
import uuid
from pathlib import Path

from geonexus.geocard import GeoCard
from geonexus.geomcp import GeoMCPServer
from geonexus.mcp_adapter import run_stdio
from geonexus.model import ModelBackend
from geonexus.model.invocation import ModelOutcome
from geonexus.recipe import Recipe, RecipeRegistry
from geonexus.resource import ComputeCapability

from .core import file_digest, inside, read_json, validate_arguments


def build_node(package: Path, artifacts: Path) -> GeoMCPServer:
    artifacts.mkdir(parents=True, exist_ok=True)
    cards = {
        card["id"]: GeoCard.model_validate(card)
        for card in (read_json(path) for path in (package / "cards").glob("*.json"))
    }
    for card in cards.values():
        card.validate()
    data = read_json(package / "data/chip.geojson")
    weights = read_json(package / "model/weights.json")
    manifest = read_json(package / "manifest.json")
    for path in ("data/chip.geojson", "model/weights.json"):
        if file_digest(package / path) != manifest["files"][path]:
            raise ValueError("Execution asset digest differs from the installed lock.")

    def save(value, name):
        key = uuid.uuid4().hex
        path = artifacts / key
        path.mkdir()
        (path / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return f"artifact://fixture/{key}/{name}"

    def load(ref):
        if not ref.startswith("artifact://fixture/"):
            raise ValueError("Artifact is not owned by this fixture node.")
        path = inside(artifacts, ref.removeprefix("artifact://fixture/"))
        return read_json(path)

    def features(params):
        value = json.loads(json.dumps(data))
        for item in value["features"]:
            red, nir = item["properties"]["red"], item["properties"]["nir"]
            item["properties"]["ndvi"] = (nir - red) / max(nir + red, 1e-9)
        return {
            "features_ref": save(value, "features.json"),
            "count": len(value["features"]),
        }

    class LogisticProvider:
        name = "fixture"

        def supports(self, card):
            return card.id == "fixture.logistic"

        def invoke(self, invocation):
            validate_arguments(
                cards["fixture.logistic"].to_dict()["x-geonexus"]["input_schema"],
                invocation.inputs,
            )
            value = load(invocation.inputs["features_ref"])
            threshold = invocation.params.get("threshold", 0.6)
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))
                or not 0 <= threshold <= 1
            ):
                raise ValueError("threshold must be between 0 and 1")
            counts = {"positive": 0, "negative": 0}
            for item in value["features"]:
                p = 1 / (
                    1
                    + math.exp(
                        -(weights["intercept"] + weights["weight"] * item["properties"]["ndvi"])
                    )
                )
                label = int(p >= threshold)
                item["properties"].update(probability=round(p, 6), classification=label)
                counts["positive" if label else "negative"] += 1
            return ModelOutcome(
                outputs={
                    "classification_ref": save(value, "classification.geojson"),
                    "summary": {
                        **counts,
                        "count": len(value["features"]),
                        "threshold": threshold,
                        "synthetic": True,
                    },
                }
            )

    backend = ModelBackend(
        cards={"fixture.logistic": cards["fixture.logistic"]},
        providers={"fixture": LogisticProvider()},
        capabilities=[
            ComputeCapability(node_url="service://fixture-node", cpu=1, memory_gb=0.25, gpu="none")
        ],
    )
    recipes = RecipeRegistry()
    recipes.register(Recipe.model_validate(read_json(package / "recipe.json")))
    token = os.environ.get("GEONEXUS_NODE_API_KEY", "")
    server = GeoMCPServer(
        name="fixture-node",
        model_backend=backend,
        recipe_registry=recipes,
        api_keys={token} if token else set(),
    )
    for card in cards.values():
        server.register_geocard(card)
    server.register_tool("ndvi_features", features)
    server.register_tool("read_artifact", lambda params: {"content": load(params["ref"])})
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    run_stdio(build_node(args.package, args.artifacts))


if __name__ == "__main__":
    main()
