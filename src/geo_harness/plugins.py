"""Launch only application-owned plugin adapters; manifests never provide commands."""

from __future__ import annotations

import asyncio
import os
import sys

from geonexus.registration import RegistrationError

from .core import MCPConnection, inside, read_json

TRUSTED = {"org.geonexus.geokg": "geokg", "org.geonexus.qgis": "qgis", "org.geonexus.stac": "stac"}


class Lease:
    def __init__(self, connection):
        self.connection = connection

    async def request(self, *args, **kwargs):
        return await self.connection.request(*args, **kwargs)

    async def tool(self, *args, **kwargs):
        return await self.connection.tool(*args, **kwargs)

    async def close(self):
        pass


class Plugins:
    def __init__(self, workspace, products):
        self.workspace = workspace
        self.products = products
        self.connections = {}
        self.locks = {}

    def descriptor(self, product_id):
        root = self.products.active_path(product_id)
        manifest = self.products.verify(root)
        name = manifest.get("runtime")
        if not name or name not in manifest["files"]:
            raise RegistrationError("Plugin launcher must be integrity-locked")
        raw = read_json(inside(root, name))
        if (
            set(raw) != {"provider", "transport"}
            or raw["transport"] != "stdio"
            or TRUSTED.get(product_id) != raw["provider"]
        ):
            raise RegistrationError(
                "Only application-owned plugin providers can launch; arbitrary commands are prohibited"
            )
        if "plugin:launch" not in self.products.installed[product_id]["permissions"]:
            raise RegistrationError("Grant plugin launch permission first")
        return root, raw

    async def start(self, product_id):
        from mcp import StdioServerParameters

        root, raw = self.descriptor(product_id)
        lock = self.locks.setdefault(product_id, asyncio.Lock())
        async with lock:
            if product_id not in self.connections:
                env = {
                    k: v
                    for k, v in os.environ.items()
                    if k
                    in (
                        "PATH",
                        "HOME",
                        "LANG",
                        "LC_ALL",
                        "PYTHONPATH",
                        "VIRTUAL_ENV",
                        "SYSTEMROOT",
                        "GEONEXUS_QGIS_PROCESS",
                    )
                }
                if raw["provider"] == "geokg":
                    args = ["-m", "geokg.mcp_server"]
                    env["GEOKG_DATA_DIR"] = str(root / "snapshot/data")
                else:
                    directory = self.workspace / "nodes" / raw["provider"]
                    directory.mkdir(parents=True, exist_ok=True)
                    args = [
                        "-m",
                        "geonexus_plugins.service",
                        raw["provider"],
                        "--workspace",
                        str(directory),
                    ]
                conn = MCPConnection(
                    StdioServerParameters(command=sys.executable, args=args, env=env)
                )
                try:
                    await conn.request("list_tools")
                except Exception as e:
                    await conn.close()
                    raise RegistrationError(
                        "Plugin could not start; install its declared application dependency and check node configuration"
                    ) from e
                self.connections[product_id] = conn
            return {
                "product_id": product_id,
                "status": "running",
                "provider": raw["provider"],
                "transport": "official-mcp-stdio",
            }

    async def connection(self, product_id):
        await self.start(product_id)
        return Lease(self.connections[product_id])

    async def stop(self, product_id):
        lock = self.locks.setdefault(product_id, asyncio.Lock())
        async with lock:
            conn = self.connections.pop(product_id, None)
            if conn:
                await conn.close()
        return {"product_id": product_id, "status": "stopped"}

    def status(self):
        return [
            {
                "product_id": pid,
                "status": "running" if pid in self.connections else "stopped",
                "installed": bool(self.products.installed.get(pid, {}).get("enabled")),
            }
            for pid in TRUSTED
        ]

    async def close(self):
        for pid in list(self.connections):
            await self.stop(pid)
