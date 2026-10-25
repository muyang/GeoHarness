"""model_view / summarize 的单元测试（纯函数，不依赖 SDK）。"""
from __future__ import annotations

from geo_harness.map_context import MAX_FIELDS, MAX_LAYERS, model_view, summarize


def context(layer_count=3, pending=True):
    layers = []
    for index in range(layer_count):
        layers.append(
            {
                "id": f"layer-{index}",
                "name": f"图层 {index}",
                "type": "vector",
                "visible": index % 2 == 0,
                "style": {
                    "fillColor": "#0F9ED5",
                    "strokeColor": "#156082",
                    "strokeWidth": 2,
                    "noise": "drop-me",
                },
                "fields": [f"f{i}" for i in range(40)],
                "features": 147,
            }
        )
    return {
        "revision": 7,
        "viewer": "GeoLibre",
        "projection": "mercator",
        "project_name": "候鸟湿地",
        "crs": "EPSG:4326",
        "viewport": {"bbox": [89.7, -10.05, 140.8, 50.2], "center": [115, 20], "zoom": 5.4},
        "selection": {"kind": "features", "ids": ["site-0091"]},
        "observed_at": "2026-10-25T09:00:00Z",
        "viewer_connected": True,
        "layers": layers,
        "active_tool": {"id": "layer.style", "state": "armed", "args": {"layer_id": "layer-0"}},
        "pending_actions": [
            {"id": "a1", "action": "layer.style", "status": "pending", "arguments": {"layer_id": "layer-0"}, "commands": []},
            {"id": "a2", "action": "view.set", "status": "pending", "arguments": {}, "commands": []},
        ],
    }


def test_model_view_keeps_core_fields():
    view = model_view(context())
    assert view["revision"] == 7
    assert view["viewport"]["bbox"] == [89.7, -10.05, 140.8, 50.2]
    assert view["selection"]["ids"] == ["site-0091"]
    assert view["active_tool"]["id"] == "layer.style"
    assert view["active_tool"]["state"] == "armed"


def test_model_view_trims_layers_fields_and_pending():
    view = model_view(context(layer_count=MAX_LAYERS + 5))
    assert len(view["layers"]) == MAX_LAYERS
    assert view["layer_count"] == MAX_LAYERS + 5
    assert len(view["layers"][0]["fields"]) == MAX_FIELDS
    assert len(view["pending_actions"]) == 2
    assert set(view["pending_actions"][0]) == {"id", "action", "status"}


def test_model_view_keeps_only_known_style_keys():
    style = model_view(context())["layers"][0]["style"]
    assert style == {"fillColor": "#0F9ED5", "strokeColor": "#156082", "strokeWidth": 2}
    assert "noise" not in style


def test_model_view_preserves_redacted_selection():
    base = context()
    base["selection"] = None
    base["viewport"] = {}
    view = model_view(base)
    assert view["selection"] is None and view["viewport"] == {}


def test_model_view_handles_empty_context():
    view = model_view(None)
    assert view["layer_count"] == 0 and view["layers"] == []
    assert view["active_tool"] == {"id": None, "state": "idle", "args": {}}


def test_summary_is_bounded_and_mentions_tool():
    text = summarize(context())
    assert "layer.style" in text
    assert "fillColor" in text
    assert len(text) <= 1200


def test_summary_truncates():
    text = summarize(context(layer_count=MAX_LAYERS), max_chars=30)
    assert len(text) == 30 and text.endswith("…")
