"""Request signatures and workspace identity routing, without network sockets."""
import asyncio
import hashlib
import hmac
import json
import time

import httpx
import pytest
from starlette.responses import JSONResponse

from geo_harness.gateway import WorkspaceGateway


KEY = "shared-gateway-test-key"


def signed(path, principal="member-a", token="member-a-private", *, stamp=None, host="127.0.0.1:9305", method="GET", platform_base=None):
    stamp = str(stamp if stamp is not None else int(time.time()))
    proof = [stamp, method, path, principal, hashlib.sha256(token.encode()).hexdigest()]
    if platform_base: proof.append(platform_base)
    message = "\n".join(proof)
    headers = {"X-Geo-Workbench-Principal": principal, "X-Geo-Platform-Token": token,
        "X-Geo-Workbench-Time": stamp, "X-Geo-Workbench-Signature": hmac.new(KEY.encode(), message.encode(), hashlib.sha256).hexdigest(),
        "X-Forwarded-Prefix": "/api/workbench/runtime", "X-Forwarded-Host": host, "X-Forwarded-Proto": "http"}
    if platform_base: headers['X-Geo-Platform-Base'] = platform_base
    return headers


def setup():
    calls = []; workspace_values = {}
    association = {"key": "a" * 32, "principal": "member-a", "token": "member-a-private"}

    async def local(scope, receive, send):
        await JSONResponse({"surface": "local"})(scope, receive, send)

    def factory(principal, token):
        calls.append((principal, token))
        workspace_values.setdefault(principal, {"owner": principal, "notes": "private for " + principal})
        async def child(scope, receive, send):
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            await JSONResponse({"workspace": workspace_values[principal], "root_path": scope.get("root_path"),
                "path": scope["path"], "host": headers.get("host"), "platform_token_header_present": "x-geo-platform-token" in headers})(scope, receive, send)
        return child

    middleware = WorkspaceGateway(local, key=KEY, factory=factory, local_account=lambda: association,
        root_cookie=("root-client-session", "root-private-cookie"))
    return middleware, calls, workspace_values, association


def test_signed_principals_route_to_isolated_workspaces_without_disclosing_tokens():
    async def check():
        gateway, calls, workspaces, _ = setup()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://testserver") as client:
            first = await client.get("/api/workbench/context?mode=actual", headers=signed("/api/workbench/context?mode=actual"))
            assert first.status_code == 200
            assert first.json()["root_path"] == "/api/workbench/runtime"
            assert first.json()["host"] == "127.0.0.1:9305"
            assert first.json()["platform_token_header_present"] is False
            assert "member-a-private" not in first.text
            second = await client.get("/api/workbench/context", headers=signed("/api/workbench/context", "member-b", "member-b-private"))
            assert second.status_code == 200
            assert second.json()["workspace"]["owner"] == "member-b"
            assert "private for member-a" not in second.text
            assert calls == [("member-a", "member-a-private"), ("member-b", "member-b-private")]
            assert len(workspaces) == 2
    asyncio.run(check())


@pytest.mark.parametrize("change", ["signature", "time", "principal", "token", "path", "query", "host", "missing_principal"])
def test_forged_or_expired_gateway_identity_never_creates_a_workspace(change):
    async def check():
        gateway, calls, _, _ = setup(); path = "/api/workbench/context?q=valid"; headers = signed(path)
        if change == "signature": headers["X-Geo-Workbench-Signature"] = "wrong"
        elif change == "time": headers = signed(path, stamp=int(time.time()) - 120)
        elif change == "principal": headers["X-Geo-Workbench-Principal"] = "admin"
        elif change == "token": headers["X-Geo-Platform-Token"] = "different-private-token"
        elif change == "path": path = "/api/settings"
        elif change == "query": path = "/api/workbench/context?q=changed"
        elif change == "host": headers = signed(path, host="attacker.example")
        else: headers.pop("X-Geo-Workbench-Principal")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://testserver") as client:
            response = await client.get(path, headers=headers)
            assert response.status_code == 403
            assert not calls
            assert "private" not in response.text
    asyncio.run(check())


def test_proxy_percent_encoded_paths_use_the_same_signature_bytes_as_node_gateway():
    async def check():
        gateway, calls, _, _ = setup()
        path = "/api/files/%E5%9C%B0%E5%9B%BE.geojson?layer=city%3A1"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://testserver") as client:
            response = await client.get(path, headers=signed(path))
            assert response.status_code == 200
            assert response.json()["path"] == "/api/workbench/runtime/api/files/地图.geojson"
            assert calls == [("member-a", "member-a-private")]
    asyncio.run(check())


@pytest.mark.parametrize("principal", ["ruoyi:1", "ruoyi:123", "legacy-member"])
def test_signed_namespaced_id_keeps_exact_workspace_identity(principal):
    async def check():
        gateway, calls, _, _ = setup()
        path = "/api/workbench/platform-results/map"
        headers = signed(path, principal, method="POST", host="127.0.0.1:3301")
        platform_base = "http://127.0.0.1:3301"
        headers["X-Geo-Platform-Base"] = platform_base
        proof = "\n".join([headers["X-Geo-Workbench-Time"], "POST", path, principal,
                            hashlib.sha256(b"member-a-private").hexdigest(), platform_base])
        headers["X-Geo-Workbench-Signature"] = hmac.new(KEY.encode(), proof.encode(), hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://testserver") as client:
            response = await client.post(path, headers=headers, json={"execution_id": "existing-result"})
            assert response.status_code == 200
            assert response.json()["workspace"]["owner"] == principal
            assert calls == [(principal, "member-a-private")]
            headers["X-Geo-Workbench-Principal"] = "ruoyi:999"
            assert (await client.post(path, headers=headers)).status_code == 403
            assert len(calls) == 1
    asyncio.run(check())


@pytest.mark.parametrize("principal", ["ruoyi/1", "ruoyi:1\nadmin", "ruoyi:1 admin", "", "x" * 129])
def test_invalid_principal_is_rejected_even_with_a_matching_signature(principal):
    async def check():
        gateway, calls, _, _ = setup()
        path = "/api/session"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://testserver") as client:
            assert (await client.get(path, headers=signed(path, principal))).status_code == 403
            assert not calls
    asyncio.run(check())


def test_local_client_needs_root_cookie_and_exact_linked_account_for_shared_workspace():
    async def check():
        gateway, calls, _, _ = setup()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://testserver") as client:
            assert (await client.get("/accounts/" + "a" * 32 + "/api/workbench/context")).status_code == 401
            assert not calls
            client.cookies.set("root-client-session", "root-private-cookie")
            assert (await client.get("/accounts/" + "b" * 32 + "/api/workbench/context")).status_code == 401
            assert not calls
            response = await client.get("/accounts/" + "a" * 32 + "/api/workbench/context")
            assert response.status_code == 200
            assert response.json()["root_path"] == "/accounts/" + "a" * 32
            assert response.json()["path"] == "/accounts/" + "a" * 32 + "/api/workbench/context"
            assert response.json()["workspace"]["owner"] == "member-a"
            assert "member-a-private" not in response.text
    asyncio.run(check())


def test_client_bookmark_after_restart_returns_to_root_without_disclosing_workspace():
    async def check():
        gateway, calls, _, _ = setup()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url='http://testserver') as client:
            response = await client.get('/accounts/'+'a'*32+'/', follow_redirects=False)
            assert response.status_code == 303 and response.headers['location'] == '/'
            response = await client.get('/accounts/'+'a'*32+'/api/session')
            assert response.status_code == 401 and response.json()['login_url'] == '/'
            assert not calls
    asyncio.run(check())


def test_client_can_link_a_ruoyi_account_to_the_same_scoped_workspace(tmp_path):
    from fastapi.testclient import TestClient
    from geo_harness.app import create_app
    app = create_app(tmp_path)
    app.state.resource_nodes.credentials['platform'] = 'private-platform-session'
    app.state.resource_nodes.transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'user': {'id': 'ruoyi:12', 'name': 'Member', 'scopes': ['workbench:run']}}))
    with TestClient(app) as client:
        client.get('/')
        csrf = client.get('/api/session').json()['csrf']
        response = client.post('/api/workbench/link-platform', json={'confirm': True}, headers={'X-Geo-CSRF': csrf})
        assert response.status_code == 200, response.text
        identity = hashlib.sha256(b'ruoyi:12').hexdigest()[:32]
        assert identity in app.state.children
        assert app.state.children[identity].state.resource_nodes.credentials['platform'] == 'private-platform-session'
        assert 'private-platform-session' not in response.text


def test_actual_signed_embedded_session_needs_no_local_cookie_and_does_not_inherit_root_credentials(tmp_path, monkeypatch):
    from geo_harness.app import create_app
    monkeypatch.setenv("GEONEXUS_HARNESS_GATEWAY_KEY", KEY)

    async def check():
        app = create_app(tmp_path)
        app.state.settings.value["llm"]["api_key"] = "root-private-llm-credential"
        app.state.resource_nodes.credential("platform", {"token": "root-private-platform-credential"})
        app.state.workbench.state["project"]["name"] = "ROOT PRIVATE MAP"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            assert (await client.get("/api/bootstrap")).status_code == 401
            response = await client.get("/api/bootstrap", headers=signed("/api/bootstrap"))
            assert response.status_code == 200
            body = response.json()
            for asset, kind in [("/ui/style.css", "text/css"), ("/ui/workbench.js", "javascript")]:
                static = await client.get(asset, headers=signed(asset))
                assert static.status_code == 200
                assert kind in static.headers["content-type"]
                assert len(static.content) > 100
            assert not body["settings"]["llm"]["api_key_configured"]
            assert "root-private" not in response.text and "member-a-private" not in response.text
            context = await client.get("/api/workbench/context", headers=signed("/api/workbench/context"))
            assert context.status_code == 200 and "ROOT PRIVATE MAP" not in context.text
            path = "/api/workbench/action"
            args = {"action": "view.set", "arguments": {"center": [120, 30]}, "expected_revision": 0}
            unsigned_csrf = await client.post(path, headers=signed(path, method="POST"), json=args)
            assert unsigned_csrf.status_code == 403
            bad_origin = await client.post(path, headers={**signed(path, method="POST"), "X-Geo-CSRF": body["csrf"], "Origin": "https://attacker.example"}, json=args)
            assert bad_origin.status_code == 403
            applied = await client.post(path, headers={**signed(path, method="POST"), "X-Geo-CSRF": body["csrf"], "Origin": "http://127.0.0.1:9305"}, json=args)
            assert applied.status_code == 200 and applied.json()["status"] == "pending"
            other = await client.get("/api/workbench/context", headers=signed("/api/workbench/context", "member-b", "member-b-private"))
            assert other.status_code == 200 and other.json()["revision"] == 0
            forbidden = await client.post("/api/resource-nodes/platform/credential", headers={**signed("/api/resource-nodes/platform/credential", method="POST"), "X-Geo-CSRF": body["csrf"], "Origin": "http://127.0.0.1:9305"}, json={"token": "replacement-admin"})
            assert forbidden.status_code == 400
            assert app.state.resource_nodes.credentials["platform"] == "root-private-platform-credential"
            child = app.state.children[hashlib.sha256(b"member-a").hexdigest()[:32]]
            assert child.state.resource_nodes.credentials["platform"] == "member-a-private"
            for scope in [app, *app.state.children.values()]:
                await scope.state.workbench.close(); await scope.state.plugins.close(); await scope.state.runtime.close()
    asyncio.run(check())
