import asyncio
import hashlib
import json
import stat

import httpx
import pytest
from fastapi.testclient import TestClient

from geo_harness.account import PlatformAccount
from geo_harness.app import create_app
from geo_harness.core import Products, read_json
from geo_harness.resource_nodes import NodeHTTPError, ResourceNodes


class Identity:
    def __init__(self):
        self.token = 'expired'
        self.user = {'id': 'ruoyi:12', 'name': 'Researcher', 'scopes': ['workbench:run']}
        self.refreshes = 0
        self.revoked = False

    def __call__(self, request):
        if request.url.path == '/api/auth/login':
            body = json.loads(request.content)
            if body['password'] != 'correct-password':
                return httpx.Response(401, json={'error': 'private upstream error'})
            self.token = 'fresh-access'
            return httpx.Response(200, json={'token': self.token, 'refresh_token': 'private-refresh', 'user': self.user})
        if request.url.path == '/api/auth/refresh':
            self.refreshes += 1
            if self.revoked:
                return httpx.Response(401, json={})
            assert json.loads(request.content) == {'refresh_token': 'private-refresh'}
            self.token = 'renewed-access'
            return httpx.Response(200, json={'token': self.token, 'refresh_token': 'rotated-refresh'})
        if request.url.path == '/api/auth/me':
            if self.revoked or self.token == 'expired' or request.headers.get('Authorization') != 'Bearer '+self.token:
                return httpx.Response(401, json={})
            return httpx.Response(200, json={'user': self.user})
        return httpx.Response(404, json={})


def setup_account(tmp_path):
    nodes = ResourceNodes(tmp_path, Products(tmp_path))
    peer = Identity()
    nodes.transport = httpx.MockTransport(peer)
    account = PlatformAccount(tmp_path, nodes)
    return account, nodes, peer


def test_launcher_health_does_not_require_a_browser_cookie_or_follow_account_redirects(tmp_path):
    app = create_app(tmp_path)
    def unexpected(request):
        raise AssertionError('A liveness probe must not contact Platform identity')
    app.state.resource_nodes.credentials['platform'] = 'private-old-access'
    app.state.resource_nodes.transport = httpx.MockTransport(unexpected)
    with TestClient(app) as client:
        response = client.get('/health')
        assert response.status_code == 200 and response.json()['status'] == 'ok'
        assert 'private-old-access' not in response.text and 'ruoyi:' not in response.text


def test_unified_login_profile_blocks_legacy_root_apis_and_uses_only_scoped_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('GEOHARNESS_REQUIRE_LOGIN', '1')
    app = create_app(tmp_path)
    app.state.settings.value['llm']['api_key'] = 'root-legacy-private-key'
    app.state.resource_nodes.transport = httpx.MockTransport(Identity())
    with TestClient(app) as client:
        client.get('/')
        session = client.get('/api/session').json()
        assert 'settings' not in session
        headers = {'X-Geo-CSRF': session['csrf']}
        assert client.get('/api/settings').status_code == 401
        assert client.post('/api/chat', json={'message':'hello'}, headers=headers).status_code == 401
        response = client.post('/api/account/login', json={'username':'member','password':'correct-password'}, headers=headers)
        assert response.status_code == 200
        prefix = response.json()['workspace_url'].split('?')[0]
        client.get(prefix)
        settings = client.get(prefix+'api/settings')
        assert settings.status_code == 200 and not settings.json()['llm']['api_key_configured']
        assert 'root-legacy-private-key' not in settings.text
        assert client.get('/api/settings').status_code == 401


def test_expired_access_refreshes_once_for_concurrent_requests_and_rotates_private_token(tmp_path):
    async def check():
        account, nodes, peer = setup_account(tmp_path)
        account.save({'token': 'expired', 'refresh_token': 'private-refresh'})
        users = await asyncio.gather(*(account.ensure() for _ in range(8)))
        assert all(u['id'] == 'ruoyi:12' for u in users)
        assert peer.refreshes == 1
        assert account.session['refresh_token'] == 'rotated-refresh'
        assert stat.S_IMODE(account.path.stat().st_mode) == 0o600
        assert nodes.credentials['platform'] == 'renewed-access'
    asyncio.run(check())


def test_revoked_refresh_removes_client_secrets_and_requires_login(tmp_path):
    async def check():
        account, nodes, peer = setup_account(tmp_path)
        account.save({'token': 'expired', 'refresh_token': 'private-refresh'})
        peer.revoked = True
        with pytest.raises(NodeHTTPError) as exc:
            await account.ensure()
        assert exc.value.status == 401
        assert not account.path.exists() and 'platform' not in nodes.credentials
    asyncio.run(check())


def test_identity_change_never_opens_old_workspace(tmp_path):
    async def check():
        account, nodes, peer = setup_account(tmp_path)
        await account.login({'username': 'member', 'password': 'correct-password'})
        account.hint.write_text(json.dumps({'principal': 'ruoyi:999'}))
        with pytest.raises(NodeHTTPError):
            await account.ensure()
        assert not account.hint.exists() and not nodes.credentials.get('platform')
    asyncio.run(check())


def test_client_login_logout_and_relogin_preserve_account_data_and_hide_tokens(tmp_path):
    app = create_app(tmp_path)
    peer = Identity()
    app.state.resource_nodes.transport = httpx.MockTransport(peer)
    with TestClient(app) as client:
        assert '使用 Platform 账号登录' in client.get('/').text
        csrf = client.get('/api/session').json()['csrf']
        headers = {'X-Geo-CSRF': csrf}
        body = {'username': 'member', 'password': 'correct-password', 'endpoint': 'https://attacker.example'}
        assert client.post('/api/account/login', json=body).status_code == 403
        response = client.post('/api/account/login', json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert 'private-refresh' not in response.text and 'fresh-access' not in response.text
        key = hashlib.sha256(b'ruoyi:12').hexdigest()[:32]
        child = app.state.children[key]
        child.state.settings.save({'llm': {'model': 'preserved-model'}})
        client.get(response.json()['workspace_url'])
        project = client.get('/accounts/'+key+'/api/workbench/project')
        assert project.status_code == 200 and project.json()['layers'] == []
        assert not child.state.products.installed.get('org.geonexus.geolibre')
        assert client.get('/accounts/'+key+'/api/session').status_code == 200
        assert client.post('/api/account/logout', json={}, headers=headers).status_code == 200
        assert client.get('/accounts/'+key+'/api/session').status_code == 401
        assert not (tmp_path/'private-platform-session.json').exists()
        assert client.post('/api/account/login', json=body, headers=headers).status_code == 200
        assert child.state.settings.value['llm']['model'] == 'preserved-model'
        assert 'correct-password' not in ''.join(p.read_text() for p in tmp_path.glob('private-*.json'))


def test_running_client_revalidates_platform_session_before_returning_private_workspace(tmp_path):
    app = create_app(tmp_path)
    peer = Identity()
    app.state.resource_nodes.transport = httpx.MockTransport(peer)
    with TestClient(app) as client:
        client.get('/')
        headers = {'X-Geo-CSRF': client.get('/api/session').json()['csrf']}
        result = client.post('/api/account/login', json={'username': 'member', 'password': 'correct-password'}, headers=headers).json()
        path = result['workspace_url'].split('?')[0]+'api/session'
        peer.revoked = True
        response = client.get(path)
        assert response.status_code == 401 and response.json()['login_required']
        assert 'preserved-model' not in response.text


@pytest.mark.parametrize('response,message', [
    (httpx.Response(404, json={}), 'HTTP 404'),
    (httpx.Response(200, text='<html>Portal</html>'), '未返回有效 JSON'),
])
def test_platform_diagnostics_distinguish_wrong_route_and_html_portal(tmp_path, response, message):
    async def check():
        _, nodes, _ = setup_account(tmp_path)
        nodes.transport = httpx.MockTransport(lambda r: response)
        with pytest.raises(Exception, match=message):
            await nodes.request(nodes.platform, 'GET', '/api/auth/me')
    asyncio.run(check())
