"""Add an explicit result channel to existing SDGNode demo packages, preserving locks.

Run with --workspace, --mcp-endpoint and --artifact-endpoint. No ports are inferred.
Only verified original 0.2.2 demo bindings with the specified endpoint are upgraded.
"""

import argparse
import json
from pathlib import Path

from geo_harness.core import Products, file_digest, read_json
from geo_harness.resource_nodes import endpoint


def upgrade(workspace, mcp_url, artifact_url):
    products = Products(Path(workspace).resolve())
    mcp_url, artifact_url = endpoint(mcp_url), endpoint(artifact_url)
    updated = []
    for path in products.market.glob("local.sdgnode.real.*/manifest.json"):
        manifest = products.verify(path.parent)
        old_digest = file_digest(path)
        binding_path = path.parent / manifest["binding"]
        binding = read_json(binding_path)
        card_id = binding.get("context", {}).get("skill")
        expected = {
            "transport": "streamable-http",
            "endpoint": mcp_url,
            "tool": "geo_execute",
            "tools": ["geo_execute"],
            "context": {"skill": card_id, "geocards": [card_id]},
        }
        if (
            manifest["version"] != "0.2.2"
            or binding != expected
            or not str(card_id).startswith("sdg.")
        ):
            continue
        binding["artifact_endpoint"] = artifact_url
        binding_path.write_text(json.dumps(binding, ensure_ascii=False, indent=2) + "\n")
        manifest["files"][manifest["binding"]] = file_digest(binding_path)
        manifest["version"] = "0.2.3"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        saved = products.installed.get(manifest["id"])
        if saved and saved["enabled"] and saved["digest"] == old_digest:
            # Same approved permissions, new immutable package; the previous lock is retained.
            products.install(manifest["id"], saved["permissions"])
        updated.append(manifest["id"])
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--mcp-endpoint", required=True)
    parser.add_argument("--artifact-endpoint", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            upgrade(args.workspace, args.mcp_endpoint, args.artifact_endpoint),
            ensure_ascii=False,
            indent=2,
        )
    )
