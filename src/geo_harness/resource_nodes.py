"""User-configured resource sources; immutable Platform and declarative GeoCard snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from geonexus.geocard import GeoCard, effective_visibility, validate_card_schema
from geonexus.registration import RegistrationError, safe_url

from .core import (
    HTTPMCPTransport,
    MCPConnection,
    file_digest,
    read_json,
    validate_arguments,
    write_private,
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def endpoint(value):
    value = safe_url(str(value).strip()).rstrip("/")
    parts = urlsplit(value)
    if parts.query or len(value) > 1000:
        raise RegistrationError("节点地址不能包含查询参数。")
    try:
        ip = ipaddress.ip_address(parts.hostname)
    except ValueError:
        ip = None
    if ip and (
        ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.is_reserved and not ip.is_loopback)
    ):
        raise RegistrationError("不允许连接链路本地、元数据或保留地址。")
    return value


class ResourceNodes:
    def __init__(
        self, workspace: Path, products, platform_url="http://127.0.0.1:9305", transport=None
    ):
        self.products, self.transport = products, transport
        self.path = workspace / "resource-nodes.json"
        self.private_path = workspace / "private-resource-nodes.json"
        self.external = read_json(self.path, {})
        self.credentials = read_json(self.private_path, {})
        self._request_platform = ContextVar("platform-request-context", default=None)
        self._platform = {
            "id": "platform",
            "name": "Platform",
            "endpoint": endpoint(platform_url),
            "protocol": "platform",
            "protected": True,
        }
        self.observations, self.entries, self.discoveries = {}, {}, {}

    @property
    def platform(self):
        active = self._request_platform.get()
        return {**self._platform, 'endpoint': active['endpoint']} if active else self._platform

    def credential_value(self, identity):
        active = self._request_platform.get()
        return active['token'] if identity == 'platform' and active else self.credentials.get(identity)

    def node(self, identity):
        if identity == "platform":
            return self.platform
        if identity not in self.external:
            raise RegistrationError("节点已移除或不存在；已安装快照仍保留，调用已停止。")
        return self.external[identity]

    def public(self):
        return [
            {
                **n,
                **self.observations.get(n["id"], {}),
                "credential_configured": bool(self.credential_value(n["id"])),
            }
            for n in [self.platform, *self.external.values()]
        ]

    async def check_address(self, target):
        # LAN/loopback are deliberate user-selected nodes. Link-local metadata services are excluded.
        if self.transport is None:
            try:
                addresses = await asyncio.to_thread(
                    socket.getaddrinfo,
                    urlsplit(target).hostname,
                    urlsplit(target).port or (443 if target.startswith("https:") else 80),
                    type=socket.SOCK_STREAM,
                )
                for address in addresses:
                    ip = ipaddress.ip_address(address[4][0])
                    if (
                        ip.is_link_local
                        or ip.is_multicast
                        or ip.is_unspecified
                        or (ip.is_reserved and not ip.is_loopback)
                    ):
                        raise RegistrationError("不允许连接链路本地、元数据或保留地址。")
            except OSError as exc:
                raise RegistrationError("无法解析节点地址。") from exc

    async def request(self, node, method, path, *, body=None, authenticated=False):
        target = node["endpoint"] + path
        await self.check_address(target)
        headers = {"Accept-Encoding": "identity"}
        if authenticated and self.credential_value(node["id"]):
            key = self.credential_value(node["id"])
            headers["Authorization" if node["protocol"] == "platform" else "X-API-Key"] = (
                "Bearer " if node["protocol"] == "platform" else ""
            ) + key
        try:
            async with (
                httpx.AsyncClient(
                    transport=self.transport, trust_env=False, follow_redirects=False, timeout=30
                ) as client,
                client.stream(method, target, json=body, headers=headers) as response,
            ):
                if response.status_code in {401, 403}:
                    raise RegistrationError(
                        "节点要求身份或权限；请配置此节点凭据，或在 Platform 检查调用授权。"
                    )
                response.raise_for_status()
                parts, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 4 * 1024 * 1024:
                        raise RegistrationError("节点返回超过 4 MiB，已停止读取。")
                    parts.append(chunk)
                return json.loads(b"".join(parts))
        except (httpx.HTTPError, ValueError) as exc:
            raise RegistrationError("节点接口不可用或未返回有效 JSON；未执行安装或计算。") from exc

    async def read_catalog(self, node):
        if node["protocol"] == "platform":
            rows, offset = [], 0
            while True:
                page = await self.request(
                    node, "GET", f"/api/v1/geocards?offset={offset}&limit=100"
                )
                items = page.get("items")
                if not isinstance(items, list) or len(items) > 100:
                    raise RegistrationError("Platform 资源目录格式错误。")
                rows.extend(items)
                offset += len(items)
                if offset >= page.get("total", offset):
                    break
                if not items or offset >= 1000:
                    raise RegistrationError("目录超过 1000 项或分页未前进。")
            return rows
        if node["protocol"] == "mcp-http":
            await self.check_address(node["endpoint"])
            headers = (
                {"X-API-Key": self.credentials[node["id"]]}
                if self.credentials.get(node["id"])
                else {}
            )
            conn = MCPConnection(HTTPMCPTransport(node["endpoint"], headers))
            try:
                available = (await conn.request("list_tools")).tools
                if not any(t.name == "geo_describe" for t in available):
                    raise RegistrationError(
                        "标准 MCP 服务未提供 geo_describe；请先发布 GeoCard 目录。"
                    )
                payload = await conn.tool("geo_describe", {})
            except RegistrationError:
                raise
            except Exception as exc:
                raise RegistrationError(
                    "标准 MCP 服务发现失败，请检查协议、地址或服务版本。"
                ) from exc
            finally:
                await conn.close()
            tools = payload.get("skills", [])
        else:
            health = await self.request(node, "GET", "/health", authenticated=True)
            if health.get("protocol") != "geomcp" or health.get("status") != "ok":
                raise RegistrationError("此地址不是可用的 GeoMCP 能力节点。")
            caps = await self.request(node, "GET", "/capabilities", authenticated=True)
            envelope = await self.request(
                node,
                "POST",
                "/geomcp",
                authenticated=True,
                body={"jsonrpc": "2.0", "id": "discover", "method": "geo.describe", "params": {}},
            )
            if envelope.get("id") != "discover" or envelope.get("error"):
                raise RegistrationError("节点未返回有效的 geo.describe 目录。")
            payload = envelope.get("result", {})
            tools = caps.get("tools", []) + payload.get("skills", [])
        cards = payload.get("geocards", [])
        if (
            not isinstance(cards, list)
            or len(cards) > 1000
            or not isinstance(tools, list)
            or len(tools) > 1000
        ):
            raise RegistrationError("节点能力目录格式或数量不符合要求。")
        rows = []
        by_id = {c.get("id"): c for c in cards if isinstance(c, dict)}

        def visible(card):
            def lookup(identity):
                child = by_id.get(identity)
                return GeoCard.from_dict(child) if child else None

            report = effective_visibility(GeoCard.from_dict(card), lookup)
            return report.visible and report.is_visible_to(["public"])

        for card in cards:
            if not visible(card):
                continue
            tool = next((t for t in tools if t.get("geocard_id", t.get("name")) == card["id"]), {})
            schema = tool.get("input_schema", {})
            executable = bool(tool.get("name") and schema.get("type") == "object")
            rows.append(
                {
                    "geocard": card,
                    "kind": "Solution"
                    if card.get("type") == "workflow" and card.get("recipe_ref")
                    else card["type"].title(),
                    "node_ref": node["id"],
                    "state": {
                        "mode": "External",
                        "node_name": node["name"],
                        "executable": executable,
                        "tool": tool.get("name"),
                        "input_schema": schema,
                        "output_schema": tool.get("output_schema"),
                        "synthetic": bool(schema.get("x-geonexus-synthetic")),
                    },
                }
            )
        return rows

    def normalize(self, node, rows):
        entries = []
        for row in rows:
            card = row.get("geocard", {})
            report = validate_card_schema(card)
            if not report.valid:
                raise RegistrationError(
                    "节点 GeoCard Schema 校验失败：" + "; ".join(report.errors)[:250]
                )
            identity = "federated." + digest([node["id"], row.get("node_ref"), card["id"]])[:24]
            static_contract = {
                "geocard": card,
                "node_ref": row.get("node_ref"),
                "tool": row.get("state", {}).get("tool"),
                "input_schema": row.get("state", {}).get("input_schema"),
                "output_schema": row.get("state", {}).get("output_schema"),
            }
            entries.append(
                {
                    **row,
                    "id": identity,
                    "source_id": node["id"],
                    "source_name": node["name"],
                    "name": card["name"],
                    "description": card.get("description", ""),
                    "version": "0.2.0",
                    "contract_digest": digest(static_contract),
                    "permissions": ["connector:read"]
                    + (
                        ["connector:execute"]
                        if row.get("state", {}).get("executable")
                        and row.get("state", {}).get("tool")
                        else []
                    ),
                    "installed": self.products.installed.get(identity),
                }
            )
        if len({e["id"] for e in entries}) != len(entries):
            raise RegistrationError("节点包含重复的资源身份。")
        return entries

    async def refresh(self):
        values = []

        async def one(node):
            try:
                entries = self.normalize(node, await self.read_catalog(node))
                self.observations[node["id"]] = {
                    "reachable": True,
                    "count": len(entries),
                    "observed_at": time.time(),
                    "error": None,
                }
                return entries
            except Exception as exc:
                self.observations[node["id"]] = {
                    "reachable": False,
                    "count": 0,
                    "observed_at": time.time(),
                    "error": str(exc)
                    if isinstance(exc, RegistrationError)
                    else "节点目录格式或服务响应不兼容。",
                }
                return []

        for entries in await asyncio.gather(
            *(one(n) for n in [self.platform, *self.external.values()])
        ):
            values.extend(entries)
        self.entries = {e["id"]: e for e in values}
        return {"items": values, "nodes": self.public()}

    async def discover(self, body):
        protocol = body.get("protocol", "geomcp-http")
        if protocol not in {"geomcp-http", "mcp-http"}:
            raise RegistrationError("第三方节点支持 GeoMCP HTTP 或标准 MCP HTTP。")
        target = endpoint(body.get("endpoint", ""))
        if target == self.platform["endpoint"] or any(
            n["endpoint"] == target for n in self.external.values()
        ):
            raise RegistrationError("此节点已配置。默认 Platform 不可重复登记。")
        node = {
            "id": "node-" + digest([target, protocol])[:16],
            "name": str(body.get("name") or "第三方 GeoNode").strip()[:120],
            "endpoint": target,
            "protocol": protocol,
            "protected": False,
        }
        entries = self.normalize(node, await self.read_catalog(node))
        token = uuid.uuid4().hex
        self.discoveries[token] = (time.time(), node)
        return {
            "discovery_id": token,
            "node": node,
            "count": len(entries),
            "executable_count": sum(bool(e["state"].get("tool")) for e in entries),
        }

    def add(self, token):
        observed = self.discoveries.pop(token, None)
        if not observed or time.time() - observed[0] > 300:
            raise RegistrationError("发现记录已过期；请重新发现节点。")
        node = observed[1]
        if len(self.external) >= 20 or any(
            n["endpoint"] == node["endpoint"] for n in self.external.values()
        ):
            raise RegistrationError("节点重复或超过 20 个节点上限。")
        self.external[node["id"]] = node
        write_private(self.path, self.external)
        return node

    def change(self, identity, action, body):
        if identity == "platform":
            raise RegistrationError("Platform 是受保护的默认节点，不可修改或删除。")
        node = self.node(identity)
        if action == "rename":
            name = str(body.get("name", "")).strip()
            if not name or len(name) > 120:
                raise RegistrationError("填写 1–120 字的节点名称。")
            node["name"] = name
        elif action == "remove":
            self.external.pop(identity)
            self.credentials.pop(identity, None)
            write_private(self.private_path, self.credentials)
            self.entries = {k: v for k, v in self.entries.items() if v["source_id"] != identity}
        else:
            raise RegistrationError("不支持的节点操作。更换入口须重新发现。")
        write_private(self.path, self.external)
        return {"ok": True}

    def credential(self, identity, body):
        self.node(identity)
        if body.get("clear"):
            self.credentials.pop(identity, None)
        elif str(body.get("token", "")).strip():
            self.credentials[identity] = str(body["token"]).strip()
        write_private(self.private_path, self.credentials)
        return {"configured": bool(self.credentials.get(identity))}

    def package(self, identity):
        entry = self.entries.get(identity)
        if not entry:
            raise RegistrationError("资源不在最新目录中；请刷新后安装。")
        root = self.products.market / identity
        binding = {
            "transport": "resource-node",
            "source_id": entry["source_id"],
            "card_id": entry["geocard"]["id"],
            "node_ref": entry.get("node_ref"),
            "tool": entry["state"].get("tool"),
            "input_schema": entry["state"].get("input_schema"),
            "output_schema": entry["state"].get("output_schema"),
            "contract_digest": entry["contract_digest"],
            "endpoint": self.node(entry["source_id"])["endpoint"],
        }
        write_private(root / "card.json", entry["geocard"])
        write_private(root / "binding.json", binding)
        write_private(
            root / "manifest.json",
            {
                "manifest_version": "0.1",
                "id": identity,
                "version": "0.2.0",
                "name": entry["name"],
                "description": entry["description"],
                "kind": "resource",
                "catalog_snapshot": True,
                "visibility": "public",
                "cards": ["card.json"],
                "binding": "binding.json",
                "skills": [],
                "dependencies": [],
                "permissions": entry["permissions"],
                "license": entry["geocard"]["license"],
                "files": {
                    "card.json": file_digest(root / "card.json"),
                    "binding.json": file_digest(root / "binding.json"),
                },
            },
        )
        self.products.verify(root)
        return entry

    async def invoke(self, binding, arguments):
        node = self.node(binding["source_id"])
        if node["endpoint"] != binding["endpoint"]:
            raise RegistrationError("安装绑定的节点入口已变化。")
        fresh = self.normalize(node, await self.read_catalog(node))
        entry = next(
            (
                e
                for e in fresh
                if e["geocard"]["id"] == binding["card_id"]
                and e.get("node_ref") == binding["node_ref"]
            ),
            None,
        )
        if not entry or entry["contract_digest"] != binding["contract_digest"]:
            raise RegistrationError("资源已撤回或契约已改变，请刷新目录并重新安装。")
        self.node(binding["source_id"])
        record = self.products.installed.get(entry["id"], {})
        if not record.get("enabled") or "connector:execute" not in record.get("permissions", []):
            raise RegistrationError("资源已停用或调用授权已撤回。")
        if not entry["state"].get("executable") or not binding.get("tool"):
            raise RegistrationError(
                "此资源可安装目录快照，但尚未配置可调用工具。内置 Demo 请在 Platform 工作台使用。"
            )
        validate_arguments(binding["input_schema"], arguments)
        if node["protocol"] == "platform":
            return await self.request(
                node,
                "POST",
                "/api/v1/node-executions",
                authenticated=True,
                body={
                    "node_ref": binding["node_ref"],
                    "card_ref": binding["card_id"],
                    "arguments": arguments,
                    "authorized": True,
                },
            )
        payload = {
            "skill": binding["tool"],
            "geocards": [binding["card_id"]],
            "params": arguments,
            "request_id": uuid.uuid4().hex,
        }
        if node["protocol"] == "mcp-http":
            headers = (
                {"X-API-Key": self.credentials[node["id"]]}
                if self.credentials.get(node["id"])
                else {}
            )
            conn = MCPConnection(HTTPMCPTransport(node["endpoint"], headers))
            try:
                return await conn.tool("geo_execute", payload)
            finally:
                await conn.close()
        call_id = uuid.uuid4().hex
        result = await self.request(
            node,
            "POST",
            "/geomcp",
            authenticated=True,
            body={"jsonrpc": "2.0", "id": call_id, "method": "geo.execute", "params": payload},
        )
        if (
            result.get("id") != call_id
            or result.get("error")
            or not isinstance(result.get("result"), dict)
        ):
            raise RegistrationError("节点调用失败；未返回成功结果。")
        if result["result"].get("status") not in {None, "ok", "succeeded"}:
            raise RegistrationError("节点报告执行失败，未生成成功结果。")
        return result["result"]
