import asyncio
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient
from geonexus.registration import RegistrationError

from geo_harness.app import create_app
from geo_harness.core import Products, Settings, read_json
from geo_harness.fixtures import DEMO_ID, MAP_ID, seed_market
from geo_harness.runtime import Runtime


def installed(path):
    products = Products(path)
    seed_market(products.market)
    for item in products.catalog():
        products.install(item["id"], item["permissions"])
    return products


def test_lifecycle_permissions_integrity_and_rollback(tmp_path):
    p = Products(tmp_path)
    seed_market(p.market)
    with pytest.raises(RegistrationError):
        p.install(DEMO_ID, [])
    p.install(DEMO_ID, ["workspace:artifacts", "fixture:execute"])
    original = p.installed[DEMO_ID]["digest"]
    source = p.source(DEMO_ID)
    manifest = read_json(source / "manifest.json")
    manifest["version"] = "0.1.1"
    (source / "manifest.json").write_text(json.dumps(manifest))
    p.install(DEMO_ID, manifest["permissions"])
    assert p.installed[DEMO_ID]["digest"] != original
    assert p.rollback(DEMO_ID)["digest"] == original
    (p.active_path(DEMO_ID) / "data/chip.geojson").write_text("{}")
    with pytest.raises(RegistrationError, match="integrity"):
        p.active_path(DEMO_ID)
    (tmp_path / "run-output.json").write_text("keep")
    p.disable(DEMO_ID, uninstall=True)
    assert (tmp_path / "run-output.json").exists()


def test_no_traversal(tmp_path):
    p = Products(tmp_path)
    seed_market(p.market)
    root = p.source(MAP_ID)
    manifest = read_json(root / "manifest.json")
    manifest["files"]["../outside.json"] = "sha256:abc"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RegistrationError):
        p.verify(root)


def test_llm_private_file_redaction_and_key_preservation(tmp_path):
    s = Settings(tmp_path)
    public = s.save(
        {
            "llm": {
                "enabled": True,
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "mine",
                "api_key": "test-secret",
            }
        }
    )
    assert "test-secret" not in json.dumps(public)
    assert public["llm"]["api_key_configured"] and os.stat(s.path).st_mode & 0o777 == 0o600
    s.save({"llm": {"api_key": "", "model": "new"}})
    assert s.value["llm"]["api_key"] == "test-secret"
    s.save({"llm": {"clear_api_key": True}})
    assert not s.value["llm"]["api_key"]


@pytest.mark.asyncio
async def test_llm_request_uses_selected_configuration(tmp_path, monkeypatch):
    s = Settings(tmp_path)
    s.save(
        {
            "llm": {
                "enabled": True,
                "base_url": "https://llm.example.org/v1",
                "model": "selected",
                "api_key": "test-key",
            }
        }
    )
    original = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    await s.completion([{"role": "user", "content": "test"}])
    assert str(seen[0].url) == "https://llm.example.org/v1/chat/completions"
    assert json.loads(seen[0].content)["model"] == "selected"
    assert seen[0].headers["authorization"] == "Bearer test-key"


def test_local_api_session_csrf_origin(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/settings").status_code == 401
        assert client.get("/").status_code == 200
        token = client.get("/api/bootstrap").json()["csrf"]
        assert client.post("/api/settings", json={}).status_code == 403
        assert (
            client.post(
                "/api/settings",
                json={},
                headers={"X-Geo-CSRF": token, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        result = client.post(
            "/api/settings", json={"llm": {"api_key": "secret"}}, headers={"X-Geo-CSRF": token}
        )
        assert result.status_code == 200 and "secret" not in result.text
        assert client.get("/api/settings", headers={"Host": "evil.example"}).status_code == 403


@pytest.mark.asyncio
async def test_official_mcp_replay_and_geolibre(tmp_path):
    p = installed(tmp_path)
    rt = Runtime(tmp_path, p)
    try:
        with pytest.raises(RegistrationError):
            await rt.plan({"threshold": 2})
        a = await rt.start({"threshold": 0.6})
        await asyncio.gather(*list(rt.jobs.values()))
        assert a["status"] == "completed"
        assert a["summary"] == {
            "positive": 35,
            "negative": 61,
            "count": 96,
            "threshold": 0.6,
            "synthetic": True,
        }
        b = await rt.start({"threshold": 0.6})
        await asyncio.gather(*list(rt.jobs.values()))
        assert a["output_digest"] == b["output_digest"]
        c = await rt.start({"threshold": 0.9})
        await asyncio.gather(*list(rt.jobs.values()))
        assert c["summary"]["positive"] < a["summary"]["positive"]
        pytest.importorskip("geolibre")
        for renderer in ["maplibre", "cesium"]:
            project = await rt.map_project(a["id"], renderer)
            assert project["project"]["primaryRenderer"] == renderer
            assert len(project["project"]["layers"]) == 1
            assert len(project["project"]["layers"][0]["geojson"]["features"]) == 96
    finally:
        await rt.close()
    p.disable(DEMO_ID)
    with pytest.raises(RegistrationError):
        await rt.plan({})


def test_agent_cannot_execute_without_per_turn_grant(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    p = app.state.products
    item = next(item for item in p.catalog() if item["id"] == DEMO_ID)
    p.install(DEMO_ID, item["permissions"])
    app.state.settings.save(
        {
            "llm": {
                "enabled": True,
                "base_url": "https://llm.example.org/v1",
                "model": "chosen-model",
                "api_key": "test-key",
            }
        }
    )
    original = httpx.AsyncClient
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "case_run",
                                            "arguments": '{"threshold":0.6}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "需要本次对话执行授权。test-key"}}
                ]
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    with TestClient(app) as client:
        client.get("/")
        token = client.get("/api/bootstrap").json()["csrf"]
        response = client.post(
            "/api/chat",
            json={"message": "解释案例", "allow_execution": False},
            headers={"X-Geo-CSRF": token},
        )
        assert response.status_code == 200
        assert not app.state.runtime.runs
        assert "test-key" not in response.json()["answer"]
        assert "case_run" not in [item["function"]["name"] for item in requests[0]["tools"]]
        assert "synthetic-wetland" in json.dumps(requests[0]["messages"])
        assert "未授权" in requests[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_real_streamable_http_auth_and_transport(tmp_path):
    import socket
    import threading
    import time

    import uvicorn
    from geonexus.geomcp import GeoMCPServer
    from geonexus.mcp_adapter import create_streamable_http_app

    from geo_harness.core import HTTPMCPTransport, MCPConnection

    node = GeoMCPServer(name="http-test", api_keys={"node-key"})
    node.register_tool("double", lambda params: {"value": params["value"] * 2})
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(
            create_streamable_http_app(node), host="127.0.0.1", port=port, log_level="error"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started
    denied = MCPConnection(HTTPMCPTransport(f"http://127.0.0.1:{port}/mcp", {}))
    allowed = MCPConnection(
        HTTPMCPTransport(f"http://127.0.0.1:{port}/mcp", {"X-API-Key": "node-key"})
    )
    try:
        assert (await denied.tool("geo_health", {}))["status"] == "ok"
        with pytest.raises(Exception) as error:
            await denied.tool("geo_execute", {"skill": "double", "params": {"value": 3}})
        assert "error response" in str(error.value)
        # The transport normalizes HTTP failures into MCPError; assert the HTTP boundary separately.
        async with httpx.AsyncClient() as raw:
            response = await raw.post(
                f"http://127.0.0.1:{port}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "geo_execute",
                        "arguments": {"skill": "double", "params": {"value": 3}},
                    },
                },
            )
        assert response.status_code == 401
        assert (await allowed.tool("geo_execute", {"skill": "double", "params": {"value": 3}}))[
            "outputs"
        ]["value"] == 6
    finally:
        await denied.close()
        await allowed.close()
        server.should_exit = True
        thread.join(timeout=5)
