"""Platform-owned identity; local storage contains tokens, never passwords."""
import asyncio
from geonexus.registration import RegistrationError

from .core import read_json, write_private
from .gateway import PRINCIPAL
from .resource_nodes import NodeHTTPError


class PlatformAccount:
    def __init__(self, workspace, nodes):
        self.nodes = nodes
        self.path = workspace / 'private-platform-session.json'
        self.hint = workspace / 'private-account-link.json'
        self.session = read_json(self.path, {})
        self.lock = asyncio.Lock()

    async def raw(self, method, path, body=None, authenticated=False):
        return await self.nodes.request(self.nodes.platform, method, path, body=body,
                                        authenticated=authenticated, _session=False)

    def save(self, result):
        token = result.get('token') or result.get('access_token')
        if not isinstance(token, str) or not token:
            raise RegistrationError('Platform 未返回有效登录凭据。')
        self.nodes.credential('platform', {'token': token})
        self.session = {k: result[k] for k in ('refresh_token', 'expiresAt') if result.get(k)}
        write_private(self.path, self.session)

    async def login(self, body):
        async with self.lock:
            result = await self.raw('POST', '/api/auth/login', {
                'username': str(body.get('username') or body.get('email') or ''),
                'password': str(body.get('password') or '')})
            self.save(result)
            self.hint.unlink(missing_ok=True)
            return {'authenticated': True, 'expires_at': result.get('expiresAt')}

    async def ensure(self):
        async with self.lock:
            if not self.nodes.credentials.get('platform'):
                raise NodeHTTPError('请使用 Platform 账号登录客户端。', 401)
            try:
                result = await self.raw('GET', '/api/auth/me', authenticated=True)
            except NodeHTTPError as exc:
                if exc.status != 401 or not self.session.get('refresh_token'):
                    raise
                try:
                    renewed = await self.raw('POST', '/api/auth/refresh', {'refresh_token': self.session['refresh_token']})
                    self.save(renewed)
                    result = await self.raw('GET', '/api/auth/me', authenticated=True)
                except NodeHTTPError as failure:
                    if failure.status in {400, 401, 403}:
                        self.clear()
                    raise
            user = result.get('user', result)
            principal = str(user.get('id', ''))
            if not PRINCIPAL.fullmatch(principal):
                raise RegistrationError('Platform 没有返回有效账号身份。')
            expected = read_json(self.hint, {}).get('principal')
            if expected and principal != expected:
                self.clear()
                raise NodeHTTPError('账号身份已变化，请重新登录客户端。', 401)
            permissions = user.get('scopes', user.get('permissions', []))
            if not user.get('isAdmin') and '*' not in permissions and 'workbench:run' not in permissions:
                raise NodeHTTPError('当前 Platform 账号没有工作台运行权限。', 403)
            return user

    def clear(self):
        self.session = {}
        self.nodes.credential('platform', {'clear': True})
        self.path.unlink(missing_ok=True)
        self.hint.unlink(missing_ok=True)
