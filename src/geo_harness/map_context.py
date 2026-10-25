"""MapContext v1 — structured map state shared by the workbench and the client.

The runtime keeps one MapContext per thread: viewport, basemap, visible layers
(with their styling), current selection, the active tool and the time window.
The model only ever sees a compact summary; the full object is persisted so a
run can be reproduced later.

Only the standard library is used so the module can be tested without the
product/SDK dependencies that ``core`` pulls in.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

THREAD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ROOTS = ("view", "basemap", "layers", "selection", "active_tool", "time")
OPS = ("replace", "add", "remove")
TOOL_STATES = ("idle", "armed", "running", "done", "error")
SELECTION_KINDS = ("none", "feature", "features", "extent")
TIME_MODES = ("single", "range")


class MapContextError(ValueError):
    """Raised when a context or a patch is malformed."""


def blank(thread_id: str) -> dict[str, Any]:
    if not THREAD_ID.match(thread_id or ""):
        raise MapContextError(f"非法的 thread_id: {thread_id!r}")
    return {
        "thread_id": thread_id,
        "revision": 0,
        "view": {"bbox": None, "crs": "EPSG:4326", "zoom": None, "pitch": 0, "bearing": 0},
        "basemap": None,
        "layers": [],
        "selection": {"kind": "none"},
        "active_tool": {"id": None, "state": "idle", "params": {}},
        "time": {"mode": "single", "value": None},
    }


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(context: dict[str, Any]) -> None:
    if not isinstance(context, dict):
        raise MapContextError("上下文必须是对象")
    if not THREAD_ID.match(str(context.get("thread_id", ""))):
        raise MapContextError("缺少或非法的 thread_id")
    revision = context.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise MapContextError("revision 必须是非负整数")

    view = context.get("view")
    if not isinstance(view, dict):
        raise MapContextError("view 必须是对象")
    bbox = view.get("bbox")
    if bbox is not None and not (
        isinstance(bbox, (list, tuple)) and len(bbox) == 4 and all(_number(v) for v in bbox)
    ):
        raise MapContextError("view.bbox 必须是 [west, south, east, north]")

    layers = context.get("layers")
    if not isinstance(layers, list):
        raise MapContextError("layers 必须是数组")
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get("id"), str) or not layer["id"]:
            raise MapContextError("每个图层都需要非空 id")
        if "visible" in layer and not isinstance(layer["visible"], bool):
            raise MapContextError(f"图层 {layer['id']} 的 visible 必须是布尔值")
        style = layer.get("style")
        if style is not None and not isinstance(style, dict):
            raise MapContextError(f"图层 {layer['id']} 的 style 必须是对象")

    selection = context.get("selection")
    if not isinstance(selection, dict) or selection.get("kind") not in SELECTION_KINDS:
        raise MapContextError(f"selection.kind 必须是 {SELECTION_KINDS} 之一")

    tool = context.get("active_tool")
    if not isinstance(tool, dict) or tool.get("state") not in TOOL_STATES:
        raise MapContextError(f"active_tool.state 必须是 {TOOL_STATES} 之一")
    if not isinstance(tool.get("params"), dict):
        raise MapContextError("active_tool.params 必须是对象")

    window = context.get("time")
    if not isinstance(window, dict) or window.get("mode") not in TIME_MODES:
        raise MapContextError(f"time.mode 必须是 {TIME_MODES} 之一")


def _parts(path: str) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise MapContextError(f"patch 路径必须以 / 开头: {path!r}")
    parts = path.split("/")[1:]
    if not parts or any(part == "" for part in parts):
        raise MapContextError(f"patch 路径不合法: {path!r}")
    if parts[0] not in ROOTS:
        raise MapContextError(f"patch 路径必须以 {ROOTS} 之一开头: {path!r}")
    return parts


def _step(node: Any, key: str, path: str) -> Any:
    if isinstance(node, list):
        if not key.isdigit():
            raise MapContextError(f"数组下标必须是整数: {path!r}")
        index = int(key)
        if index < 0 or index >= len(node):
            raise MapContextError(f"数组下标越界: {path!r}")
        return node[index]
    if not isinstance(node, dict) or key not in node:
        raise MapContextError(f"路径不存在: {path!r}")
    return node[key]


def apply_patch(
    context: dict[str, Any],
    ops: list[dict[str, Any]],
    base_revision: int | None = None,
) -> dict[str, Any]:
    """Return a new context with the JSON-patch subset applied (revision + 1)."""
    validate(context)
    if not isinstance(ops, list) or not ops:
        raise MapContextError("ops 必须是非空数组")
    if base_revision is not None and int(base_revision) != context["revision"]:
        raise MapContextError(
            f"revision 不匹配：客户端 {base_revision}，服务端 {context['revision']}"
        )
    out = copy.deepcopy(context)
    for op in ops:
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise MapContextError(f"未知操作: {op!r}")
        path = op.get("path")
        parts = _parts(path)
        parent = out
        for part in parts[:-1]:
            parent = _step(parent, part, path)
        key = parts[-1]
        name = op["op"]
        if name == "remove":
            if isinstance(parent, list):
                if not key.isdigit():
                    raise MapContextError(f"数组下标必须是整数: {path!r}")
                index = int(key)
                if index < 0 or index >= len(parent):
                    raise MapContextError(f"数组下标越界: {path!r}")
                del parent[index]
            else:
                if not isinstance(parent, dict) or key not in parent:
                    raise MapContextError(f"路径不存在: {path!r}")
                del parent[key]
            continue
        if name == "add" and isinstance(parent, list) and key == "-":
            parent.append(op.get("value"))
            continue
        if isinstance(parent, list):
            if not key.isdigit():
                raise MapContextError(f"数组下标必须是整数: {path!r}")
            index = int(key)
            if name == "add":
                if index < 0 or index > len(parent):
                    raise MapContextError(f"数组下标越界: {path!r}")
                parent.insert(index, op.get("value"))
            else:
                if index < 0 or index >= len(parent):
                    raise MapContextError(f"数组下标越界: {path!r}")
                parent[index] = op.get("value")
        else:
            if not isinstance(parent, dict):
                raise MapContextError(f"无法写入: {path!r}")
            if name == "replace" and key not in parent:
                raise MapContextError(f"replace 的目标不存在: {path!r}")
            parent[key] = op.get("value")
    out["revision"] = context["revision"] + 1
    validate(out)
    return out


def _write_private(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        os.chmod(handle.name, 0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        temporary = Path(handle.name)
    temporary.replace(path)


class MapContextStore:
    """One JSON document per thread under ``<workspace>/map-context``."""

    def __init__(self, workspace: Path) -> None:
        self.root = Path(workspace) / "map-context"

    def path(self, thread_id: str) -> Path:
        if not THREAD_ID.match(thread_id or ""):
            raise MapContextError(f"非法的 thread_id: {thread_id!r}")
        return self.root / f"{thread_id}.json"

    def load(self, thread_id: str) -> dict[str, Any]:
        path = self.path(thread_id)
        if not path.exists():
            return blank(thread_id)
        context = json.loads(path.read_text(encoding="utf-8"))
        validate(context)
        return context

    def save(self, context: dict[str, Any]) -> dict[str, Any]:
        validate(context)
        _write_private(self.path(context["thread_id"]), context)
        return context

    def push(
        self,
        thread_id: str,
        ops: list[dict[str, Any]],
        base_revision: int | None = None,
    ) -> dict[str, Any]:
        context = apply_patch(self.load(thread_id), ops, base_revision)
        return self.save(context)

    def snapshot(self, thread_id: str) -> dict[str, Any]:
        """Copy for a run record; the run must not share mutable state."""
        return copy.deepcopy(self.load(thread_id))


def summarize_for_model(context: dict[str, Any], max_chars: int = 1200) -> str:
    """Compact, deterministic summary for prompt injection (≤ ~600 tokens)."""
    validate(context)
    view = context["view"]
    bbox = view.get("bbox")
    head = [
        f"地图上下文 rev {context['revision']}",
        f"视口 bbox={bbox} crs={view.get('crs')} zoom={view.get('zoom')}",
        f"底图 {context.get('basemap') or '未设置'}",
    ]
    visible = [layer for layer in context["layers"] if layer.get("visible", True)]
    if visible:
        head.append(f"可见图层 {len(visible)} 个：")
        for layer in visible[:6]:
            style = layer.get("style") or {}
            bits = []
            if style.get("ramp"):
                bits.append(f"渲染 {style['ramp']}")
            if style.get("field"):
                bits.append(f"字段 {style['field']}")
            if style.get("classBreaks"):
                bits.append(f"分级 {style['classBreaks']}")
            if style.get("palette"):
                bits.append(f"配色 {style['palette']}")
            if layer.get("opacity") is not None:
                bits.append(f"不透明度 {layer['opacity']}")
            suffix = f"：{'，'.join(bits)}" if bits else ""
            suffix += "（选中）" if layer.get("selected") else ""
            head.append(f"- {layer.get('name') or layer['id']}（{layer.get('type') or 'layer'}）{suffix}")
    else:
        head.append("可见图层：无")
    selection = context["selection"]
    head.append(f"选中：{selection.get('kind')} {selection.get('ids') or ''}".rstrip())
    tool = context["active_tool"]
    if tool.get("id"):
        head.append(f"激活工具：{tool['id']}（{tool['state']}）参数 {tool.get('params') or {}}")
    window = context["time"]
    if window.get("value"):
        head.append(f"时间窗：{window['mode']} {window['value']}")
    text = "\n".join(head)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
