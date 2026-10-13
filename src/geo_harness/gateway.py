"""Signed local Platform gateway and isolated workspaces for authenticated accounts."""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


PREFIX = '/api/workbench/runtime'


class WorkspaceGateway:
    def __init__(self, app, *, key, factory, local_account, root_cookie):
        self.app, self.key, self.factory = app, key, factory
        self.local_account, self.root_cookie = local_account, root_cookie

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope['headers']}
        principal = headers.get('x-geo-workbench-principal')
        if principal is not None:
            token = headers.get('x-geo-platform-token', '')
            stamp = headers.get('x-geo-workbench-time', '')
            path = scope.get('raw_path', scope['path'].encode()).decode('ascii')
            if scope.get('query_string'):
                path += '?' + scope['query_string'].decode()
            platform_base = headers.get('x-geo-platform-base', '')
            proof = [stamp, scope['method'], path, principal, hashlib.sha256(token.encode()).hexdigest()]
            if platform_base:
                proof.append(platform_base)
            data = '\n'.join(proof)
            expected = hmac.new(self.key.encode(), data.encode(), hashlib.sha256).hexdigest() if self.key else ''
            forwarded = headers.get('x-forwarded-host', '')
            host = urlsplit('http://' + forwarded).hostname
            try:
                valid_time = abs(time.time() - int(stamp)) <= 60
            except ValueError:
                valid_time = False
            valid_base = (not platform_base or (urlsplit(platform_base).scheme in {'http', 'https'} and platform_base == headers.get('x-forwarded-proto', 'http') + '://' + forwarded))
            if (not valid_base or not self.key or not valid_time or not token or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,128}', principal)
                    or host not in {'localhost', '127.0.0.1', '::1', 'testserver'}
                    or not hmac.compare_digest(expected, headers.get('x-geo-workbench-signature', ''))):
                return await JSONResponse({'error': '平台工作台会话签名无效或过期。'}, status_code=403)(scope, receive, send)
            child = self.factory(principal, token)
            copied = dict(scope)
            copied['geo_gateway_verified'] = True
            copied['geo_platform_token'] = token
            copied['geo_platform_base'] = platform_base
            copied['root_path'] = PREFIX
            # ASGI mounts keep the full public path; StaticFiles strips root_path.
            copied['path'] = PREFIX + scope['path']
            copied['raw_path'] = PREFIX.encode() + scope.get('raw_path', scope['path'].encode())
            copied['headers'] = [(k, v) for k, v in scope['headers'] if k.lower() not in {b'host', b'x-geo-platform-token', b'x-geo-platform-base'}]
            copied['headers'].append((b'host', forwarded.encode()))
            return await child(copied, receive, send)
        if any(k.startswith('x-geo-workbench-') or k in {'x-geo-platform-token', 'x-geo-platform-base'} for k in headers):
            return await JSONResponse({'error': '未验证的平台网关请求。'}, status_code=403)(scope, receive, send)
        match = re.match(r'^/accounts/([a-f0-9]{32})(/.*)?$', scope['path'])
        if match:
            association = self.local_account()
            cookie_name, cookie_value = self.root_cookie
            cookies = dict(part.strip().split('=', 1) for part in headers.get('cookie', '').split(';') if '=' in part)
            if (not association or match[1] != association['key'] or cookies.get(cookie_name) != cookie_value):
                return await JSONResponse({'error': '请在客户端关联当前 Platform 账号。'}, status_code=401)(scope, receive, send)
            child = self.factory(association['principal'], association['token'])
            copied = dict(scope)
            copied['root_path'] = '/accounts/' + match[1]
            return await child(copied, receive, send)
        return await self.app(scope, receive, send)
