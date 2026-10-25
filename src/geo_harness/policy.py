"""Confirmation policy for map actions and executions (pure, no I/O).

Thresholds live in the workspace settings (``confirm`` block) so operators can
adjust them from the backend; this module only decides *whether* an action needs
an explicit confirmation and *why*.  Enforcement is the caller's business.
"""

from __future__ import annotations

import math
from typing import Any

DEFAULT_CONFIRM: dict[str, Any] = {
    "enabled": True,
    "actions": ["layer.remove", "result.open"],
    "extent_area_gt": 5.0e9,
    "raster_pixels_gt": 1.0e8,
}
ACTION_NAMES = (
    "view.set",
    "view.projection",
    "layer.visibility",
    "layer.style",
    "layer.remove",
    "undo",
    "result.open",
)
METERS_PER_DEGREE = 111_320.0


class PolicyError(ValueError):
    """Raised when the confirm block is malformed."""


def normalize(value: Any) -> dict[str, Any]:
    """Return a complete, validated confirm block (missing keys get defaults)."""
    data = dict(DEFAULT_CONFIRM)
    if value is None:
        return data
    if not isinstance(value, dict):
        raise PolicyError("confirm 必须是对象")
    if "enabled" in value:
        if not isinstance(value["enabled"], bool):
            raise PolicyError("confirm.enabled 必须是布尔值")
        data["enabled"] = value["enabled"]
    if "actions" in value:
        actions = value["actions"]
        if not isinstance(actions, list) or any(a not in ACTION_NAMES for a in actions):
            raise PolicyError(f"confirm.actions 只能是 {ACTION_NAMES} 的子集")
        data["actions"] = list(dict.fromkeys(actions))
    for key in ("extent_area_gt", "raster_pixels_gt"):
        if key in value:
            number = value[key]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
                raise PolicyError(f"confirm.{key} 必须是非负有限数")
            data[key] = float(number)
    return data


def bbox_area_m2(bbox: Any) -> float:
    """Approximate geodesic area of ``[west, south, east, north]`` in m²."""
    if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
        raise PolicyError("bbox 必须是 [west, south, east, north]")
    west, south, east, north = (float(v) for v in bbox)
    if not all(math.isfinite(v) for v in (west, south, east, north)):
        raise PolicyError("bbox 必须是有限数值")
    middle = math.radians((south + north) / 2)
    width = abs(east - west) * METERS_PER_DEGREE * math.cos(middle)
    height = abs(north - south) * METERS_PER_DEGREE
    return width * height


def decide(action: str, arguments: dict[str, Any] | None, confirm: Any) -> dict[str, Any]:
    """``{"needs": bool, "reasons": [...]}``; never raises on missing numbers."""
    settings = normalize(confirm)
    if not settings["enabled"]:
        return {"needs": False, "reasons": [], "settings": settings}
    arguments = arguments or {}
    reasons: list[str] = []
    if action in settings["actions"]:
        reasons.append(f"动作 {action} 默认需要确认")
    bbox = arguments.get("bbox")
    if bbox:
        try:
            area = bbox_area_m2(bbox)
        except PolicyError:
            area = None
        if area is not None and area > settings["extent_area_gt"]:
            reasons.append(f"范围约 {area:.2e} m²，超过阈值 {settings['extent_area_gt']:.2e} m²")
    pixels = arguments.get("raster_pixels") or arguments.get("pixels")
    if isinstance(pixels, (int, float)) and not isinstance(pixels, bool):
        if pixels > settings["raster_pixels_gt"]:
            reasons.append(f"栅格约 {pixels:.2e} 像元，超过阈值 {settings['raster_pixels_gt']:.2e}")
    return {"needs": bool(reasons), "reasons": reasons, "settings": settings}
