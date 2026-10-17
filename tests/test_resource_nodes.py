import asyncio
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from geonexus.registration import RegistrationError

from geo_harness.app import create_app
from geo_harness.core import Products, read_json
from geo_harness.resource_nodes import ResourceNodes


def card(identity="public.data", sensitivity="public"):
    return {
        "geocard_version": "1.0",
        "id": identity,
        "type": "data",
        "name": "公开真实数据",
        "description": "源站版本与范围见契约",
        "tags": ["population", "2020"],
        "license": "CC-BY-4.0",
        "spatial": {"crs": "EPSG:4326"},
        "provenance": {"provider": "测试源"},
        "compliance": {"sensitivity": sensitivity},
    }


class Peer:
    def __init__(self):
        self.rows = [
            {
                "geocard": card(),
                "kind": "Data",
                "node_ref": "peer-a",
                "state": {
                    "executable": True,
                    "tool": "read_data",
                    "input_schema": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer", "maximum": 10}},
                        "additionalProperties": False,
                    },
                    "node_name": "能力节点",
                },
            }
        ]
        self.calls = []
        self.available = True
        self.status = "ok"

    def request(self, r):
        self.calls.append(
            (r.method, str(r.url), dict(r.headers), json.loads(r.content) if r.content else None)
        )
        if not self.available:
            return httpx.Response(503)
        if r.url.path.endswith("/api/v1/geocards"):
            return httpx.Response(
                200, json={"items": copy.deepcopy(self.rows), "total": len(self.rows)}
            )
        if r.url.path.endswith("/health"):
            return httpx.Response(200, json={"status": "ok", "protocol": "geomcp"})
        if r.url.path.endswith("/capabilities"):
            return httpx.Response(200, json={"tools": []})
        if r.url.path.endswith("/geomcp"):
            body = json.loads(r.content)
            if body["method"] == "geo.describe":
                skills = [
                    {
                        "name": "read_data",
                        "geocard_id": "public.data",
                        "input_schema": self.rows[0]["state"]["input_schema"],
                    }
                ]
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {
                            "geocards": [card(), card("private.data", "restricted")],
                            "skills": skills,
                        },
                    },
                )
            return httpx.Response(
                200,
                json={"id": body["id"], "result": {"status": self.status, "outputs": {"count": 2}}},
            )
        if r.url.path.endswith("/api/v1/node-executions"):
            assert json.loads(r.content)["authorized"] is True
            return httpx.Response(200, json={"status": "succeeded", "result": {"count": 2}})
        return httpx.Response(404)


def setup(tmp_path):
    p = Products(tmp_path)
    peer = Peer()
    nodes = ResourceNodes(tmp_path, p, transport=httpx.MockTransport(peer.request))
    return p, peer, nodes


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("action", ["rename", "remove", "edit", "disable", "endpoint"])
def test_default_platform_is_immutable(tmp_path, action):
    _, _, nodes = setup(tmp_path)
    with pytest.raises(RegistrationError, match="不可修改或删除"):
        nodes.change("platform", action, {"name": "hijack", "endpoint": "https://example.org"})
    assert nodes.node("platform")["endpoint"] == "http://127.0.0.1:3301"
    assert nodes.public()[0]["protected"]


def test_catalog_exact_source_schema_tags_and_static_dynamic_separation(tmp_path):
    p, peer, nodes = setup(tmp_path)
    data = run(nodes.refresh())
    item = data["items"][0]
    assert item["geocard"] == peer.rows[0]["geocard"]
    assert item["kind"] == "Data" and item["geocard"]["tags"] == ["population", "2020"]
    assert "executable" not in item["geocard"]
    original = item["contract_digest"]
    peer.rows[0]["state"]["observed_at"] = "later"
    assert run(nodes.refresh())["items"][0]["contract_digest"] == original
    nodes.package(item["id"])
    root = p.source(item["id"])
    assert read_json(root / "card.json") == peer.rows[0]["geocard"]
    assert p.verify(root)["catalog_snapshot"] is True
    with pytest.raises(RegistrationError):
        p.install(item["id"], [])
    p.install(item["id"], item["permissions"])
    assert read_json(p.active_path(item["id"]) / "card.json") == peer.rows[0]["geocard"]


def test_discovery_public_only_expiry_duplicate_and_persistence(tmp_path):
    p, peer, nodes = setup(tmp_path)
    draft = run(nodes.discover({"name": "SDGNode", "endpoint": "http://127.0.0.1:9309"}))
    assert draft["count"] == 1 and draft["executable_count"] == 1
    assert len(nodes.public()) == 1
    added = nodes.add(draft["discovery_id"])
    with pytest.raises(RegistrationError):
        nodes.add(draft["discovery_id"])
    with pytest.raises(RegistrationError):
        run(nodes.discover({"endpoint": added["endpoint"]}))
    assert ResourceNodes(tmp_path, p).node(added["id"]) == added
    draft2 = run(nodes.discover({"endpoint": "http://127.0.0.1:9311"}))
    nodes.discoveries[draft2["discovery_id"]] = (0, draft2["node"])
    with pytest.raises(RegistrationError):
        nodes.add(draft2["discovery_id"])


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/private",
        "http://name:secret@127.0.0.1",
        "http://127.0.0.1:9309/?token=secret",
        "http://127.0.0.1/#fragment",
        "http://169.254.169.254",
        "http://[fe80::1]",
    ],
)
def test_unsafe_source_addresses_rejected(tmp_path, url):
    _, peer, nodes = setup(tmp_path)
    with pytest.raises(RegistrationError):
        run(nodes.discover({"endpoint": url}))
    assert not peer.calls


def test_metadata_install_does_not_create_executable_capability(tmp_path):
    p, peer, nodes = setup(tmp_path)
    peer.rows[0]["state"] = {"executable": False}
    item = run(nodes.refresh())["items"][0]
    assert item["permissions"] == ["connector:read"]
    nodes.package(item["id"])
    p.install(item["id"], item["permissions"])
    assert "connector:execute" not in p.installed[item["id"]]["permissions"]


def test_private_credentials_not_in_catalog_snapshots_or_other_nodes(tmp_path):
    p, peer, nodes = setup(tmp_path)
    draft = run(nodes.discover({"endpoint": "http://127.0.0.1:9309"}))
    added = nodes.add(draft["discovery_id"])
    nodes.credential("platform", {"token": "platform-private"})
    nodes.credential(added["id"], {"token": "node-private"})
    data = run(nodes.refresh())
    assert "private" not in json.dumps(data)
    for item in data["items"]:
        nodes.package(item["id"])
        p.install(item["id"], item["permissions"])
        binding = read_json(p.active_path(item["id"]) / "binding.json")
        run(nodes.invoke(binding, {}))
        assert "private" not in json.dumps(p.verify(p.active_path(item["id"])))
    execution = [
        c
        for c in peer.calls
        if c[3]
        and (c[1].endswith("/api/v1/node-executions") or c[3].get("method") == "geo.execute")
    ]
    assert execution[0][2]["authorization"] == "Bearer platform-private"
    assert "x-api-key" not in execution[0][2]
    assert execution[1][2]["x-api-key"] == "node-private" and "authorization" not in execution[1][2]
    assert (tmp_path / "private-resource-nodes.json").stat().st_mode & 0o777 == 0o600
    nodes.credential("platform", {"clear": True})
    assert not nodes.public()[0]["credential_configured"]


@pytest.mark.parametrize("change", ["schema", "card", "withdraw", "grant", "remove", "disable"])
def test_revoke_or_changed_contract_stops_call(tmp_path, change):
    p, peer, nodes = setup(tmp_path)
    draft = run(nodes.discover({"endpoint": "http://127.0.0.1:9309"}))
    added = nodes.add(draft["discovery_id"])
    data = run(nodes.refresh())
    item = next(i for i in data["items"] if i["source_id"] != "platform")
    nodes.package(item["id"])
    p.install(item["id"], item["permissions"])
    binding = read_json(p.active_path(item["id"]) / "binding.json")
    if change == "schema":
        peer.rows[0]["state"]["input_schema"]["properties"]["limit"]["maximum"] = 9
    elif change == "card":
        binding["contract_digest"] = "forged"
    elif change == "withdraw":
        peer.available = False
    elif change == "grant":
        p.installed[item["id"]]["permissions"] = []
    elif change == "remove":
        nodes.change(added["id"], "remove", {})
    else:
        p.disable(item["id"])
    with pytest.raises(RegistrationError):
        run(nodes.invoke(binding, {}))
    assert not any(c[3] and c[3].get("method") == "geo.execute" for c in peer.calls)
    assert (tmp_path / "packages" / p.installed[item["id"]]["digest"][7:] / "card.json").exists()


def test_invalid_arguments_and_failed_peer_never_report_success(tmp_path):
    p, peer, nodes = setup(tmp_path)
    draft = run(nodes.discover({"endpoint": "http://127.0.0.1:9309"}))
    nodes.add(draft["discovery_id"])
    item = run(nodes.refresh())["items"][1]
    nodes.package(item["id"])
    p.install(item["id"], item["permissions"])
    binding = read_json(p.active_path(item["id"]) / "binding.json")
    with pytest.raises(RegistrationError):
        run(nodes.invoke(binding, {"limit": 100}))
    peer.status = "failed"
    with pytest.raises(RegistrationError, match="执行失败"):
        run(nodes.invoke(binding, {}))


def test_source_failure_does_not_fall_back_to_fake_platform_cards(tmp_path):
    _, peer, nodes = setup(tmp_path)
    peer.available = False
    data = run(nodes.refresh())
    assert data["items"] == [] and data["nodes"][0]["reachable"] is False


def test_http_session_csrf_protected_platform_and_install_then_execute(tmp_path):
    app = create_app(tmp_path)
    peer = Peer()
    app.state.resource_nodes.transport = httpx.MockTransport(peer.request)
    with TestClient(app) as c:
        assert c.get("/api/resource-nodes").status_code == 401
        c.get("/")
        csrf = c.get("/api/bootstrap").json()["csrf"]
        headers = {"x-geo-csrf": csrf}
        assert c.post("/api/resource-nodes/platform/remove", json={}).status_code == 403
        assert (
            c.post(
                "/api/resource-nodes/platform/rename", json={"name": "changed"}, headers=headers
            ).status_code
            == 400
        )
        item = c.get("/api/resource-catalog").json()["items"][0]
        identity = item["id"]
        assert (
            c.post(
                f"/api/resource-catalog/{identity}/install", json={"granted": []}, headers=headers
            ).status_code
            == 400
        )
        assert (
            c.post(
                f"/api/resource-catalog/{identity}/install",
                json={"granted": item["permissions"]},
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            c.post(
                f"/api/resources/{identity}/call",
                json={"arguments": {}, "confirm_execution": False},
                headers=headers,
            ).status_code
            == 400
        )
        assert (
            c.post(
                f"/api/resources/{identity}/call",
                json={"arguments": {}, "confirm_execution": True, "tool": "wrong"},
                headers=headers,
            ).status_code
            == 400
        )
        result = c.post(
            f"/api/resources/{identity}/call",
            json={"arguments": {}, "confirm_execution": True},
            headers=headers,
        )
        assert result.status_code == 200 and result.json()["status"] == "succeeded"
        assert c.get("/api/bootstrap").json()["cards"][0]["card"] == peer.rows[0]["geocard"]


def test_platform_login_uses_fixed_endpoint_and_keeps_only_token(tmp_path):
    app = create_app(tmp_path)
    seen = []

    def peer(r):
        seen.append(r)
        assert str(r.url) == "http://127.0.0.1:3301/api/auth/login"
        return httpx.Response(200, json={"token": "private-session", "expiresAt": "later"})

    app.state.resource_nodes.transport = httpx.MockTransport(peer)
    with TestClient(app) as c:
        c.get("/")
        headers = {"x-geo-csrf": c.get("/api/bootstrap").json()["csrf"]}
        r = c.post(
            "/api/resource-nodes/platform/login",
            json={
                "email": "demo@example.org",
                "password": "not-stored",
                "endpoint": "https://untrusted.example",
            },
            headers=headers,
        )
        assert r.status_code == 200 and r.json() == {"authenticated": True, "expires_at": "later"}
        assert read_json(tmp_path / "private-resource-nodes.json") == {
            "platform": "private-session"
        }
        assert "private-session" not in c.get("/api/resource-nodes").text
        assert "not-stored" not in (tmp_path / "private-resource-nodes.json").read_text()


def test_independent_client_workspaces_do_not_overwrite_browser_sessions(tmp_path):
    with TestClient(create_app(tmp_path/'first')) as first, TestClient(create_app(tmp_path/'second')) as second:
        first.get('/');second.get('/')
        one=next(iter(first.cookies.keys()));two=next(iter(second.cookies.keys()))
        assert one!=two and one!='geo_session' and two!='geo_session'
        assert first.get('/api/resource-nodes').status_code==200
        assert second.get('/api/resource-nodes').status_code==200


def test_market_call_injects_private_session_without_manual_input(tmp_path):
    app = create_app(tmp_path)
    peer = Peer()
    schema = peer.rows[0]['state']['input_schema']
    schema['properties']['session_token'] = {'type': 'string', 'pattern': '^[a-f0-9]{32}$', 'x-internal': True, 'writeOnly': True}
    schema['required'] = ['session_token']
    app.state.resource_nodes.transport = httpx.MockTransport(peer.request)
    with TestClient(app) as c:
        c.get('/')
        headers = {'x-geo-csrf': c.get('/api/bootstrap').json()['csrf']}
        item = c.get('/api/resource-catalog').json()['items'][0]
        identity = item['id']
        assert c.post(f'/api/resource-catalog/{identity}/install', json={'granted': item['permissions']}, headers=headers).status_code == 200
        response = c.post(f'/api/resources/{identity}/call', json={'arguments': {}, 'confirm_execution': True}, headers=headers)
        assert response.status_code == 200, response.text
        sent = [call[3] for call in peer.calls if call[1].endswith('/api/v1/node-executions')][-1]
        token = sent['arguments']['session_token']
        assert len(token) == 32 and token == app.state.workbench.node_session
        assert token not in response.text
        response = c.post(f'/api/resources/{identity}/call', json={'arguments': {'session_token': 'f'*32}, 'confirm_execution': True}, headers=headers)
        assert response.status_code == 200
        assert [call[3] for call in peer.calls if call[1].endswith('/api/v1/node-executions')][-1]['arguments']['session_token'] == token
