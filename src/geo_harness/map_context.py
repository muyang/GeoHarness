"""Bounded views of the live workbench map context (pure functions only).

There is exactly one source of truth for map state: ``Workbench.state`` /
``Workbench.context()``.  This module never stores state and never syncs with a
viewer; it only trims the context for a model call so a large project cannot
flood the prompt.  Keeping it pure is deliberate — no store, no patch engine.
"""

from __future__ import annotations

from typing import Any

MAX_LAYERS = 12
MAX_FIELDS = 20
MAX_PENDING = 5
STYLE_KEYS = ("fillColor", "strokeColor", "circleColor", "fillOpacity", "strokeWidth", "circleRadius")


def _style(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in STYLE_KEYS if key in value}


def _untouched(value: Any) -> Any:
    """Keep ``None``(redacted) distinct from an empty object."""
    return value


def model_view(
    context: dict[str, Any] | None,
    max_layers: int = MAX_LAYERS,
    max_fields: int = MAX_FIELDS,
    max_pending: int = MAX_PENDING,
) -> dict[str, Any]:
    """Trim a workbench context for the model without changing its meaning."""
    context = context or {}
    layers = []
    for layer in list(context.get("layers") or [])[:max_layers]:
        layers.append(
            {
                "id": layer.get("id"),
                "name": layer.get("name"),
                "type": layer.get("type"),
                "visible": layer.get("visible", True),
                "style": _style(layer.get("style")),
                "fields": list(layer.get("fields") or [])[:max_fields],
                "features": layer.get("features"),
            }
        )
    pending = [
        {"id": item.get("id"), "action": item.get("action"), "status": item.get("status")}
        for item in list(context.get("pending_actions") or [])[:max_pending]
    ]
    tool = context.get("active_tool")
    view = {
        "revision": context.get("revision"),
        "viewer": context.get("viewer"),
        "projection": context.get("projection"),
        "project_name": context.get("project_name"),
        "crs": context.get("crs"),
        "viewport": _untouched(context.get("viewport")),
        "selection": _untouched(context.get("selection")),
        "observed_at": context.get("observed_at"),
        "viewer_connected": context.get("viewer_connected"),
        "layer_count": len(context.get("layers") or []),
        "layers": layers,
        "active_tool": tool if isinstance(tool, dict) else {"id": None, "state": "idle", "args": {}},
        "pending_actions": pending,
    }
    return view


def summarize(context: dict[str, Any] | None, max_chars: int = 1200) -> str:
    """Human-readable one-block summary, used for logs and compact fallbacks."""
    view = model_view(context)
    viewport = view.get("viewport") or {}
    bbox = viewport.get("bbox") if isinstance(viewport, dict) else None
    center = viewport.get("center") if isinstance(viewport, dict) else None
    lines = [f"地图上下文 rev {view.get('revision')}（{view.get('viewer')} · {view.get('projection')}）"]
    lines.append(f"视口 bbox={bbox} center={center} crs={view.get('crs')}")
    visible = [layer for layer in view["layers"] if layer.get("visible")]
    lines.append(f"可见图层 {len(visible)}/{view.get('layer_count')}")
    for layer in visible[:6]:
        style = layer.get("style") or {}
        detail = "，".join(f"{key}={value}" for key, value in style.items())
        lines.append(f"- {layer.get('name') or layer.get('id')}（{layer.get('type')}）{detail}")
    tool = view.get("active_tool") or {}
    if tool.get("id"):
        lines.append(f"激活工具：{tool['id']}（{tool.get('state')}）参数 {tool.get('args') or {}}")
    if view.get("pending_actions"):
        lines.append("待确认动作：" + "、".join(str(item.get("action")) for item in view["pending_actions"]))
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
