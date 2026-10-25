"""Minimal, config-driven GIS command surface (T2).

Commands are a thin, validated view over installed products: execution always
goes through ``Workbench.submit`` so confirmation, digests and auditing keep a
single implementation. Adding a command is a data change, not a code change.
"""

from __future__ import annotations

from typing import Any

from geonexus.registration import RegistrationError

# id -> product tool + a small argument contract. `product_id` is resolved from
# the installed catalogue by product id; `required` are passed through verbatim.
COMMANDS: dict[str, dict[str, Any]] = {
    "geom.buffer": {"product_id": "rustgis.geom.buffer", "tool": "buffer", "required": ["distance"], "cost": 0.5, "confirm": "auto"},
    "geom.clip": {"product_id": "rustgis.geom.clip", "tool": "clip", "required": ["mask"], "cost": 0.5, "confirm": "auto"},
    "geom.dissolve": {"product_id": "rustgis.geom.dissolve", "tool": "dissolve", "required": ["by"], "cost": 0.5, "confirm": "auto"},
    "crs.reproject": {"product_id": "rustgis.crs.reproject", "tool": "reproject", "required": ["crs"], "cost": 0.5, "confirm": "auto"},
    "raster.zonal_stats": {"product_id": "node.raster.zonal_stats", "tool": "zonal_stats", "required": ["zones"], "cost": 1.0, "confirm": "always"},
    "io.export_geojson": {"product_id": "rustgis.io.export_geojson", "tool": "export_geojson", "required": [], "cost": 0.5, "confirm": "auto"},
}


class CommandRegistry:
    """Derive availability from the installed products; never stores state."""

    def __init__(self, workbench) -> None:
        self.wb = workbench

    def _resolve(self, command_id: str) -> dict[str, Any]:
        spec = COMMANDS.get(command_id)
        if not spec:
            raise RegistrationError(f"未知命令: {command_id}")
        try:
            product = self.wb.describe(spec["product_id"])
        except RegistrationError as error:
            raise RegistrationError(f"命令 {command_id} 需要的产品未安装: {error}") from None
        return {**spec, "id": command_id, "product": product}

    def list(self) -> list[dict[str, Any]]:
        items = []
        for command_id, spec in COMMANDS.items():
            try:
                self._resolve(command_id)
                available = True
            except RegistrationError:
                available = False
            items.append({"id": command_id, "tool": spec["tool"], "requires": spec["product_id"], "required": spec["required"], "available": available})
        return items

    def describe(self, command_id: str) -> dict[str, Any]:
        resolved = self._resolve(command_id)
        return {"id": command_id, "tool": resolved["tool"], "required": resolved["required"], "product": resolved["product"], "cost": resolved["cost"]}

    async def execute(self, command_id: str, arguments: dict[str, Any], *, source: str = "ui") -> dict[str, Any]:
        resolved = self._resolve(command_id)
        arguments = dict(arguments or {})
        missing = [name for name in resolved["required"] if name not in arguments]
        if missing:
            raise RegistrationError(f"命令 {command_id} 缺少参数: {', '.join(missing)}")
        if resolved["confirm"] == "always" and not arguments.get("_policy_confirm"):
            raise RegistrationError("该命令需要确认：请以 _policy_confirm=true 重试。")
        digest = resolved["product"].get("digest") or ""
        return await self.wb.submit(resolved["product_id"], arguments, digest, source=source)
