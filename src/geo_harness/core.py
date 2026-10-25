"""Product lifecycle, private settings and supervised official MCP connections."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import jsonschema
from geonexus.geocard import validate_card_schema
from geonexus.registration import RegistrationError, safe_url, validate_profile
from .llm import model_id_hint, is_model_not_found
from .policy import DEFAULT_CONFIRM, normalize


def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def write_private(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        os.chmod(handle.name, 0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = handle.name
    os.replace(temporary, path)


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not relative or Path(relative).is_absolute() or not target.is_relative_to(root.resolve()):
        raise RegistrationError("Package path escapes the package root.")
    if any(part == ".." for part in Path(relative).parts):
        raise RegistrationError("Parent traversal is prohibited.")
    return target


class Products:
    """Install immutable, hash-verified declarative products; no install scripts."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.market = workspace / "market"
        self.cache = workspace / "packages"
        self.state_path = workspace / "installed.json"
        self.market.mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.installed = read_json(self.state_path, {})

    def catalog(self) -> list[dict[str, Any]]:
        entries = []
        for path in sorted(self.market.glob("*/manifest.json")):
            manifest = self.verify(path.parent)
            entries.append(
                {
                    **manifest,
                    "package_digest": file_digest(path),
                    "installed": self.installed.get(manifest["id"]),
                }
            )
        return entries

    def source(self, product_id: str) -> Path:
        matches = [
            path.parent
            for path in self.market.glob("*/manifest.json")
            if read_json(path).get("id") == product_id
        ]
        if len(matches) != 1:
            raise RegistrationError("Product not found or product ID is ambiguous.")
        return matches[0]

    def verify(self, source: Path) -> dict[str, Any]:
        manifest = read_json(source / "manifest.json")
        if not isinstance(manifest, dict) or manifest.get("manifest_version") != "0.1":
            raise RegistrationError("Unsupported product manifest.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", manifest.get("id", "")):
            raise RegistrationError("Invalid product ID.")
        if not re.fullmatch(r"\d+\.\d+\.\d+", manifest.get("version", "")):
            raise RegistrationError("Use an exact semantic product version.")
        if manifest.get("scripts"):
            raise RegistrationError("Product install scripts are prohibited.")
        files = manifest.get("files", {})
        if not isinstance(files, dict) or len(files) > 2000:
            raise RegistrationError("A product must declare at most 2000 files.")
        for relative, expected in files.items():
            path = inside(source, relative)
            if (
                not path.is_file()
                or path.stat().st_size > 20 * 1024 * 1024
                or path.is_symlink()
                or file_digest(path) != expected
            ):
                raise RegistrationError(f"Package integrity check failed: {relative}")
        for relative in manifest.get("cards", []):
            if relative not in manifest.get("files", {}):
                raise RegistrationError("Every GeoCard must be included in the integrity manifest.")
            card = read_json(inside(source, relative))
            schema = validate_card_schema(card)
            if not schema.valid:
                raise RegistrationError("; ".join(schema.errors))
            # Published catalogue snapshots preserve the source card verbatim.
            # Their execution contract is pinned separately in the hashed binding.
            if manifest.get("catalog_snapshot"):
                if manifest.get("binding") not in files:
                    raise RegistrationError("Catalogue snapshots require a hashed node binding.")
                binding = read_json(inside(source, manifest["binding"]))
                if binding.get("transport") != "resource-node" or not binding.get(
                    "contract_digest"
                ):
                    raise RegistrationError("Invalid catalogue snapshot binding.")
            elif card["type"] in {"data", "skill", "model", "compute"}:
                report = validate_profile(card)
                if not report.valid:
                    raise RegistrationError(json.dumps(report.to_dict(), ensure_ascii=False))
        for relative in manifest.get("skills", []):
            if relative not in manifest.get("files", {}):
                raise RegistrationError(
                    "Every Agent Skill must be included in the integrity manifest."
                )
        return manifest

    def install(self, product_id: str, granted: list[str]) -> dict[str, Any]:
        source = self.source(product_id)
        manifest = self.verify(source)
        required = set(manifest.get("permissions", []))
        if not required.issubset(set(granted)):
            raise RegistrationError("Approve the requested workspace permissions before enabling.")
        for dependency in manifest.get("dependencies", []):
            current = self.installed.get(dependency["id"])
            if (
                not current
                or current["version"] != dependency["version"]
                or not current.get("enabled")
            ):
                raise RegistrationError(f"Install the exact dependency first: {dependency['id']}")
        checksum = file_digest(source / "manifest.json")
        target = self.cache / checksum[7:]
        if not target.exists():
            temporary = Path(tempfile.mkdtemp(dir=self.cache))
            try:
                # Copy only declared files; neither symlinks nor hidden executable payloads.
                for relative in manifest["files"]:
                    src = inside(source, relative)
                    dest = inside(temporary, relative)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
                shutil.copyfile(source / "manifest.json", temporary / "manifest.json")
                self.verify(temporary)
                if file_digest(temporary / "manifest.json") != checksum:
                    raise RegistrationError("Manifest changed during installation.")
                temporary.rename(target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        else:
            self.verify(target)
        previous = self.installed.get(product_id)
        record = {
            "id": product_id,
            "version": manifest["version"],
            "digest": checksum,
            "enabled": True,
            "permissions": sorted(required),
            "history": (
                [{k: v for k, v in previous.items() if k != "history"}]
                + previous.get("history", [])
            )
            if previous and previous["digest"] != checksum
            else (previous or {}).get("history", []),
        }
        self.installed[product_id] = record
        write_private(self.state_path, self.installed)
        return record

    def active_path(self, product_id: str) -> Path:
        item = self.installed.get(product_id)
        if not item or not item.get("enabled"):
            raise RegistrationError("Install and enable this product first.")
        path = self.cache / item["digest"][7:]
        manifest = self.verify(path)
        if file_digest(path / "manifest.json") != item["digest"]:
            raise RegistrationError("Installed manifest no longer matches the product lock.")
        for dep in manifest.get("dependencies", []):
            current = self.installed.get(dep["id"], {})
            if not current.get("enabled") or current.get("version") != dep["version"]:
                raise RegistrationError("An enabled exact-version dependency is required.")
        return path

    def disable(self, product_id: str, *, uninstall: bool = False) -> None:
        for key, record in self.installed.items():
            if key == product_id or not record.get("enabled"):
                continue
            manifest = self.verify(self.cache / record["digest"][7:])
            if any(dep["id"] == product_id for dep in manifest.get("dependencies", [])):
                raise RegistrationError(f"Disable dependent product first: {key}")
        if product_id not in self.installed:
            raise RegistrationError("Product is not installed.")
        if uninstall:
            del self.installed[product_id]
        else:
            self.installed[product_id]["enabled"] = False
        write_private(self.state_path, self.installed)

    def rollback(self, product_id: str) -> dict[str, Any]:
        current = self.installed.get(product_id, {})
        history = current.get("history", [])
        if not history:
            raise RegistrationError("No earlier installed version is available.")
        prior = history[0]
        path = self.cache / prior["digest"][7:]
        manifest = self.verify(path)
        if file_digest(path / "manifest.json") != prior["digest"]:
            raise RegistrationError("Rollback manifest does not match the saved lock.")
        for dep in manifest.get("dependencies", []):
            current_dep = self.installed.get(dep["id"], {})
            if not current_dep.get("enabled") or current_dep.get("version") != dep["version"]:
                raise RegistrationError("Rollback requires its exact-version dependencies.")
        self.installed[product_id] = {**prior, "history": history[1:]}
        write_private(self.state_path, self.installed)
        return self.installed[product_id]


def llm_base_url(value: str) -> str:
    """Accept either an API base or a pasted complete Chat Completions endpoint."""
    value = value.strip().rstrip('/')
    if not value:
        return ''
    safe_url(value)
    parts = urlsplit(value)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise RegistrationError('模型服务地址不能包含用户名、密码、查询参数或片段。')
    path = parts.path.rstrip('/')
    while path.endswith('/chat/completions'):
        path = path[:-len('/chat/completions')].rstrip('/')
    return urlunsplit((parts.scheme, parts.netloc, path, '', ''))


class Settings:
    def __init__(self, workspace: Path):
        self.path = workspace / 'private-settings.json'
        self.value = read_json(self.path, {'llm': {'enabled': False, 'provider': 'compatible',
            'base_url': '', 'model': '', 'api_key': '', 'temperature': 0.2}, 'viewer_url': 'local',
            'confirm': dict(DEFAULT_CONFIRM)})
        self.value['confirm'] = normalize(self.value.get('confirm'))

    def public(self) -> dict[str, Any]:
        value = json.loads(json.dumps(self.value))
        key = value['llm'].pop('api_key', '')
        value['llm']['api_key_configured'] = bool(key)
        return value

    def preview(self, request: dict[str, Any]) -> 'Settings':
        if not isinstance(request, dict):
            raise RegistrationError('模型配置必须是对象。')
        candidate = object.__new__(Settings)
        candidate.path = self.path
        candidate.value = json.loads(json.dumps(self.value))
        current = candidate.value['llm']
        incoming = request.get('llm', {})
        if not isinstance(incoming, dict):
            raise RegistrationError('LLM settings must be an object.')
        for field in ('provider', 'base_url', 'model', 'api_key'):
            if field in incoming and (not isinstance(incoming[field], str) or len(incoming[field]) > 4096):
                raise RegistrationError(f'Invalid LLM {field}.')
        if 'enabled' in incoming and not isinstance(incoming['enabled'], bool):
            raise RegistrationError('LLM enabled must be boolean.')
        for key in ('provider', 'base_url', 'model', 'enabled', 'temperature'):
            if key in incoming:
                current[key] = incoming[key].strip() if isinstance(incoming[key], str) else incoming[key]
        current['base_url'] = llm_base_url(current['base_url'])
        old_origin = urlsplit(self.value['llm'].get('base_url', ''))
        new_origin = urlsplit(current['base_url'])
        if (self.value['llm'].get('api_key') and old_origin.netloc and new_origin.netloc
                and (old_origin.scheme, old_origin.netloc) != (new_origin.scheme, new_origin.netloc)
                and not incoming.get('api_key') and not incoming.get('clear_api_key')):
            raise RegistrationError('服务地址已变更，请重新填写该服务的 API Key，避免将旧密钥发送给其他服务。')
        if incoming.get('clear_api_key'):
            current['api_key'] = ''
        elif incoming.get('api_key'):
            current['api_key'] = incoming['api_key'].strip()
        if current['model'] in {'阿里百炼', '阿里云百炼', '百炼', 'DeepSeek', 'OpenAI', 'Ollama'}:
            raise RegistrationError('模型名称需要准确模型 ID。' + model_id_hint(current['base_url']))
        if current['enabled'] and (not current['base_url'] or not current['model']):
            raise RegistrationError('请填写模型服务地址和准确模型 ID。')
        temperature = current['temperature']
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise RegistrationError('Temperature must be between 0 and 2.')
        if 'confirm' in request:
            candidate.value['confirm'] = normalize(request['confirm'])
        else:
            candidate.value['confirm'] = normalize(candidate.value.get('confirm'))
        if 'viewer_url' in request:
            value = request['viewer_url']
            if not isinstance(value, str):
                raise RegistrationError('Invalid viewer URL.')
            if value != 'local':
                safe_url(value)
            candidate.value['viewer_url'] = value.rstrip('/')
        return candidate

    def save(self, request: dict[str, Any]) -> dict[str, Any]:
        candidate = self.preview(request)
        write_private(self.path, candidate.value)
        self.value = candidate.value
        return self.public()

    async def completion(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                         *, max_tokens: int = 1500, connection_probe: bool = False, task_mode: bool = False) -> dict[str, Any]:
        config = self.value['llm']
        if not config['enabled']:
            raise RegistrationError('请先配置并启用 LLM；确定性案例仍可直接运行。')
        base = llm_base_url(config['base_url'])
        if not base or not config['model']:
            raise RegistrationError('请填写模型服务地址和准确模型 ID。')
        if config.get('provider') in {'bailian', 'bailian-coding', 'bailian-token', 'deepseek', 'openai'} and not config.get('api_key'):
            raise RegistrationError('此远程模型服务需要 API Key，请填写该入口和地域对应的有效密钥。')
        headers = {'Content-Type': 'application/json'}
        if config.get('api_key'):
            headers['Authorization'] = 'Bearer ' + config['api_key']
        body = {'model': config['model'], 'messages': messages, 'temperature': config['temperature'], 'max_tokens': max_tokens}
        if (connection_probe or task_mode) and urlsplit(base).hostname == 'token-plan.cn-beijing.maas.aliyuncs.com' and config['model'] == 'qwen3.8-flash':
            # Keep a 16-token connectivity probe from spending its output on reasoning.
            body['enable_thinking'] = False
        if tools:
            body['tools'] = tools
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10), follow_redirects=False) as client:
                response = await client.post(base + '/chat/completions', headers=headers, json=body)
        except httpx.TimeoutException:
            raise RegistrationError('模型连接超时，请检查服务地址和网络。') from None
        except httpx.RequestError:
            raise RegistrationError('无法连接模型服务，请检查网络、代理和服务地址。') from None
        if response.status_code != 200:
            if response.status_code == 404 and is_model_not_found(response):
                raise RegistrationError('模型服务返回 HTTP 404（model_not_found）：该模型 ID 不存在或当前密钥无权使用。' + model_id_hint(base))
            hints = {401: 'API Key 无效或与服务地域不匹配，请更新该入口的密钥。',
                403: '服务拒绝访问，请检查密钥类型、地域、业务空间及模型调用权限。',
                404: '请检查 API 前缀和模型 ID；无需重复填写 /chat/completions。',
                429: '请求达到限额，请检查配额、余额或稍后重试。'}
            raise RegistrationError(f'LLM service returned HTTP {response.status_code}. ' + hints.get(response.status_code, '请检查模型服务状态和模型 ID。'))
        try:
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get('choices'), list) or not data['choices'] or not isinstance(data['choices'][0].get('message'), dict):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise RegistrationError('模型响应不符合 Chat Completions 格式。') from None
        return data

    async def agent_completion(self, messages, tools=None):
        return await self.completion(messages,tools,max_tokens=2400,task_mode=True)


class MCPConnection:
    """One owner task opens and closes a persistent official MCP client."""

    def __init__(self, server: Any):
        self.server = server
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task: asyncio.Task | None = None
        self.ready: asyncio.Future | None = None

    async def start(self) -> None:
        if self.task is None:
            self.ready = asyncio.get_running_loop().create_future()
            self.task = asyncio.create_task(self._serve())
        await asyncio.wait_for(asyncio.shield(self.ready), 30)

    async def _serve(self) -> None:
        from mcp.client import Client

        try:
            async with Client(self.server) as client:
                self.ready.set_result(True)
                while True:
                    item = await self.queue.get()
                    if item is None:
                        break
                    method, args, future = item
                    if future.cancelled():
                        continue
                    try:
                        result = await asyncio.wait_for(getattr(client, method)(**args), 60)
                        if not future.done():
                            future.set_result(result)
                    except Exception as exc:
                        if not future.done():
                            future.set_exception(exc)
        except Exception as exc:
            if self.ready and not self.ready.done():
                self.ready.set_exception(exc)
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item is not None and not item[2].done():
                    item[2].set_exception(RuntimeError("MCP connection closed."))
        finally:
            self.task = None

    async def request(self, method: str, **args: Any) -> Any:
        await self.start()
        future = asyncio.get_running_loop().create_future()
        await self.queue.put((method, args, future))
        return await asyncio.wait_for(future, 65)

    async def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self.request("call_tool", name=name, arguments=arguments)
        envelope = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        if result.is_error:
            raise RegistrationError(
                "MCP tool failed: " + json.dumps(envelope, ensure_ascii=False)[:1000]
            )
        if result.structured_content is not None:
            return result.structured_content
        for block in result.content:
            if getattr(block, "type", None) == "text":
                try:
                    return json.loads(block.text)
                except ValueError:
                    pass
        return {"mcp_result": envelope}

    async def close(self) -> None:
        if self.task:
            owner = self.task
            await self.queue.put(None)
            await asyncio.wait_for(asyncio.shield(owner), 70)


def validate_arguments(schema: dict[str, Any], args: dict[str, Any]) -> None:
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(args))
    if errors:
        raise RegistrationError("; ".join(error.message for error in errors))


class HTTPMCPTransport:
    """Official SDK Streamable HTTP transport with a separate node credential."""

    def __init__(self, url: str, headers: dict[str, str]):
        self.url, self.headers = url, headers
        self.stack = AsyncExitStack()

    async def __aenter__(self):
        import httpx2
        from mcp.client.streamable_http import streamable_http_client

        client = await self.stack.enter_async_context(httpx2.AsyncClient(headers=self.headers))
        streams = await self.stack.enter_async_context(
            streamable_http_client(self.url, http_client=client)
        )
        return streams

    async def __aexit__(self, *args):
        return await self.stack.__aexit__(*args)
