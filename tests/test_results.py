"""Real artifact contract, local viewer and private presentation boundaries."""

import asyncio
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from geonexus.registration import RegistrationError
from test_resource_nodes import setup

from geo_harness.app import create_app
from geo_harness.core import read_json
from geo_harness.fixtures import MAP_ID
from geo_harness.results import Results, geographic_preview

GEO = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [114.3, 30.6]},
            "properties": {"name": "真实要素"},
        }
    ],
}


def run(coro):
    return asyncio.run(coro)


def installed_result(tmp_path, content=b"data", platform=True):
    p, peer, nodes = setup(tmp_path)
    item = run(nodes.refresh())["items"][0]
    if not platform:
        discovery = run(nodes.discover({"endpoint": "http://127.0.0.1:9309"}))
        added = nodes.add(discovery["discovery_id"])
        item = next(x for x in run(nodes.refresh())["items"] if x["source_id"] == added["id"])
    nodes.package(item["id"])
    p.install(item["id"], item["permissions"])
    results = Results(tmp_path, p, nodes)
    a = {
        "name": "raster.tif",
        "href": "/results/" + "a" * 32 + "/raster.tif",
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }
    result = {
        "id": "b" * 32,
        "status": "succeeded",
        "result": {
            "status": "ok",
            "outputs": {
                "preview": GEO,
                "synthetic": False,
                "artifacts": [a],
                "provenance": {"provider": "真实数据源"},
            },
        },
    }
    rec = results.save(item["id"], "read_data", result)
    return p, peer, nodes, results, rec, a


def test_result_history_persistence_and_geojson_bounds(tmp_path):
    p, _, nodes, results, r, _ = installed_result(tmp_path)
    assert results.list(r["product_id"])[0]["id"] == r["id"]
    assert Results(tmp_path, p, nodes).record(r["id"])["provenance"] == {"provider": "真实数据源"}
    assert (results.root / r["id"] / "result.json").stat().st_mode & 0o777 == 0o600
    assert geographic_preview({"preview": GEO})[1] == [114.3, 30.6, 114.3, 30.6]
    with pytest.raises(RegistrationError):
        results.record("../private")


@pytest.mark.parametrize(
    "geometry,crs", [([114, 300], None), ([114, float("inf")], None), ([114, 30], "EPSG:3857")]
)
def test_non_geographic_coordinates_are_not_relabelled(geometry, crs):
    fc = json.loads(json.dumps(GEO))
    fc["features"][0]["geometry"]["coordinates"] = geometry
    if crs:
        fc["crs"] = crs
    with pytest.raises(RegistrationError):
        geographic_preview({"preview": fc})


def test_stac_footprint_does_not_embed_signed_assets():
    fc, bbox = geographic_preview(
        {
            "items": [
                {
                    "id": "scene",
                    "geometry": GEO["features"][0]["geometry"],
                    "properties": {"datetime": "2020"},
                    "assets": {"red": {"href": "https://example.org?token=private"}},
                }
            ]
        }
    )
    assert bbox and "private" not in json.dumps(fc)


@pytest.mark.parametrize("platform", [True, False])
def test_artifact_is_fetched_only_from_pinned_gateway_and_verified(tmp_path, platform):
    _, _, nodes, results, r, a = installed_result(tmp_path, platform=platform)
    seen = []
    nodes.credentials[r.get("source_id", "platform")] = "local-secret"

    def fetch(req):
        seen.append(req)
        return httpx.Response(200, content=b"data")

    nodes.transport = httpx.MockTransport(fetch)
    path = run(results.artifact(r["id"], a["name"]))
    assert path.read_bytes() == b"data"
    expected = (
        "/api/v1/node-executions/" + "b" * 32 + "/artifacts/raster.tif" if platform else a["href"]
    )
    assert seen[0].url.path == expected
    assert path.stat().st_mode & 0o777 == 0o600
    run(results.artifact(r["id"], a["name"]))
    assert len(seen) == 1
    path.write_bytes(b"tampered")
    with pytest.raises(RegistrationError, match="校验失败"):
        run(results.artifact(r["id"], a["name"]))


@pytest.mark.parametrize("content,status", [(b"xxxx", 200), (b"datax", 200), (b"", 302)])
def test_bad_hash_oversize_and_redirect_are_rejected(tmp_path, content, status):
    _, _, nodes, results, r, a = installed_result(tmp_path)
    nodes.transport = httpx.MockTransport(
        lambda req: httpx.Response(
            status, content=content, headers={"location": "http://other/private"}
        )
    )
    with pytest.raises(RegistrationError):
        run(results.artifact(r["id"], a["name"]))
    assert not (results.root / r["id"] / "artifacts" / a["name"]).exists()


def test_absolute_artifact_url_and_withdrawn_install_rejected_before_network(tmp_path):
    p, peer, _, results, r, a = installed_result(tmp_path)
    a["href"] = "http://other/private"
    with pytest.raises(RegistrationError, match="结果路径"):
        run(results.fetch_artifact(r, a))
    p.disable(r["product_id"])
    with pytest.raises(RegistrationError):
        run(results.fetch_artifact(r, a))
    assert all("other" not in c[1] for c in peer.calls)


def test_private_result_project_session_and_viewer_lifecycle(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as c:
        c.get("/")
        state = c.get("/api/bootstrap").json()
        headers = {"X-Geo-CSRF": state["csrf"]}
        viewer = next(p for p in state["catalog"] if p["id"] == MAP_ID)
        assert viewer["cards"] == ["card.json"] and viewer["version"] == "0.2.1"
        assert viewer["visibility"] == "public"
        assert state["settings"]["viewer_url"] == "local"
        assert (
            c.post(
                f"/api/products/{MAP_ID}/install",
                json={"granted": viewer["permissions"]},
                headers=headers,
            ).status_code
            == 200
        )
        p, _, nodes, results, r, _ = installed_result(tmp_path / "different")
        # Write a local result in the app's own protected store; no test server mock is passed to the browser.
        product = app.state.products
        record = Results(tmp_path, product, nodes)
        r["artifacts"] = []  # This test exercises an inline vector, without a raster download.
        folder = record.root / r["id"]
        folder.mkdir(parents=True)
        (folder / "record.json").write_text(json.dumps(r))
        (folder / "result.json").write_text(json.dumps({"outputs": {"preview": GEO}}))
        response = c.post(f"/api/resource-results/{r['id']}/map", json={}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["viewer_url"].startswith("http://testserver/viewer/?url=")
        project = c.get(response.json()["project_url"]).json()
        assert project["layers"][0]["geojson"] == GEO
        assert project["metadata"]["viewer"] == "opengeos/GeoLibre"
        # Private projects have no anonymous /shared route and cannot bypass the cookie.
        c.cookies.clear()
        assert c.get(response.json()["project_url"]).status_code == 401
        c.get("/")
        c.post(f"/api/products/{MAP_ID}/disable", json={}, headers=headers)
        assert c.get(response.json()["project_url"]).status_code == 400


def test_real_geotiff_layer_uses_authenticated_local_artifact_and_actual_crs(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    file = tmp_path / "input.tif"
    with rasterio.open(
        file,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs="EPSG:32650",
        transform=from_origin(206200, 2470000, 100, 100),
    ) as src:
        src.write(np.ones((1, 10, 10), dtype="float32"))
    _, _, nodes, results, r, a = installed_result(tmp_path / "store", file.read_bytes())
    nodes.transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=file.read_bytes())
    )
    # Install the separately packaged GeoLibre product; raster bytes are never a remote image URL.
    from geo_harness.fixtures import seed_market

    seed_market(results.products.market)
    m = results.products.verify(results.products.source(MAP_ID))
    results.products.install(MAP_ID, m["permissions"])
    source = results.root / r["id"] / "result.json"
    data = read_json(source)
    del data["result"]["outputs"]["preview"]
    source.write_text(json.dumps(data))
    view = run(results.map(r["id"], "http://testserver"))
    project = read_json(results.root / r["id"] / "map.geolibre.json")
    assert len(project["layers"]) == 1 and project["layers"][0]["type"] == "xyz"
    assert project["layers"][0]["source"]["url"].startswith(
        "http://testserver/api/resource-results/"
    )
    assert 114 < view["bounds"][0] < 115 and 22 < view["bounds"][1] < 23


def test_declared_mcp_artifact_channel_never_infers_ports_or_forwards_key(tmp_path):
    from geo_harness.core import file_digest

    p, _, nodes, results, r, a = installed_result(tmp_path, platform=False)
    source = p.source(r["product_id"])
    manifest = read_json(source / "manifest.json")
    binding = read_json(source / "binding.json")
    binding = {
        "transport": "streamable-http",
        "endpoint": "http://127.0.0.1:9310/mcp",
        "artifact_endpoint": "http://127.0.0.1:9309",
        "tool": "geo_execute",
    }
    (source / "binding.json").write_text(json.dumps(binding))
    manifest["files"]["binding.json"] = file_digest(source / "binding.json")
    manifest.pop("catalog_snapshot", None)
    card = read_json(source / "card.json")
    card["access"] = {"protocol": "mcp", "endpoint": "http://127.0.0.1:9310/mcp"}
    card["x-geonexus"] = {
        "revision": "0.2.3",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    }
    (source / "card.json").write_text(json.dumps(card))
    manifest["files"]["card.json"] = file_digest(source / "card.json")
    manifest["version"] = "0.2.3"
    (source / "manifest.json").write_text(json.dumps(manifest))
    p.install(r["product_id"], manifest["permissions"])
    r["digest"] = p.installed[r["product_id"]]["digest"]
    nodes.credentials["platform"] = "must-not-leak"
    seen = []

    def fetch(req):
        seen.append(req)
        return httpx.Response(200, content=b"data")

    nodes.transport = httpx.MockTransport(fetch)
    assert run(results.fetch_artifact(r, a)) == b"data"
    assert str(seen[0].url).startswith("http://127.0.0.1:9309/results/")
    assert "authorization" not in seen[0].headers and "x-api-key" not in seen[0].headers
