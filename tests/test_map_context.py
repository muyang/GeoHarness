"""MapContext v1 单元测试（仅依赖标准库 + pytest）。"""
from __future__ import annotations

import json

import pytest

from geo_harness.map_context import (
    MapContextError,
    MapContextStore,
    apply_patch,
    blank,
    summarize_for_model,
    validate,
)


def context_with_layer():
    context = blank("t-1")
    context["view"]["bbox"] = [89.7, -10.05, 140.8, 50.2]
    context["view"]["zoom"] = 5.4
    context["basemap"] = "satellite"
    context["layers"] = [
        {
            "id": "rfi-sites",
            "name": "优先湿地站点",
            "type": "vector",
            "visible": True,
            "style": {
                "ramp": "graduated",
                "field": "irreplaceability",
                "classBreaks": [0, 0.2, 0.5, 1.0],
            },
            "opacity": 0.9,
            "selected": True,
        }
    ]
    context["active_tool"] = {"id": "terrain.slope", "state": "armed", "params": {"method": "horn"}}
    context["time"] = {"mode": "range", "value": "2025-06-01/2025-08-31"}
    return context


def test_blank_defaults_are_valid():
    context = blank("t-1")
    validate(context)
    assert context["revision"] == 0
    assert context["selection"]["kind"] == "none"
    assert context["active_tool"]["state"] == "idle"


def test_blank_rejects_bad_thread_id():
    with pytest.raises(MapContextError):
        blank("../escape")


def test_store_roundtrip(tmp_path):
    store = MapContextStore(tmp_path)
    store.save(context_with_layer())
    loaded = store.load("t-1")
    assert loaded["layers"][0]["style"]["field"] == "irreplaceability"
    assert json.loads((tmp_path / "map-context" / "t-1.json").read_text())["view"]["zoom"] == 5.4


def test_store_returns_blank_for_unknown_thread(tmp_path):
    context = MapContextStore(tmp_path).load("t-new")
    assert context["revision"] == 0 and context["layers"] == []


def test_patch_replaces_bbox_and_bumps_revision():
    context = apply_patch(
        context_with_layer(),
        [{"op": "replace", "path": "/view/bbox", "value": [100, 0, 120, 20]}],
    )
    assert context["view"]["bbox"] == [100, 0, 120, 20]
    assert context["revision"] == 1


def test_patch_appends_and_removes_layer():
    appended = apply_patch(
        context_with_layer(),
        [{"op": "add", "path": "/layers/-", "value": {"id": "rivers", "visible": True}}],
    )
    assert [layer["id"] for layer in appended["layers"]] == ["rfi-sites", "rivers"]

    removed = apply_patch(appended, [{"op": "remove", "path": "/layers/0"}])
    assert [layer["id"] for layer in removed["layers"]] == ["rivers"]


def test_patch_rejects_unknown_root_and_missing_replace_target():
    with pytest.raises(MapContextError):
        apply_patch(blank("t-1"), [{"op": "replace", "path": "/secret", "value": 1}])
    with pytest.raises(MapContextError):
        apply_patch(blank("t-1"), [{"op": "replace", "path": "/basemap-x", "value": 1}])


def test_patch_rejects_revision_mismatch():
    with pytest.raises(MapContextError, match="revision"):
        apply_patch(
            context_with_layer(),
            [{"op": "replace", "path": "/basemap", "value": "dark"}],
            base_revision=7,
        )


def test_invalid_state_is_rejected():
    context = context_with_layer()
    context["active_tool"]["state"] = "exploded"
    with pytest.raises(MapContextError):
        validate(context)


def test_summary_mentions_tool_style_and_is_bounded():
    text = summarize_for_model(context_with_layer())
    assert "terrain.slope" in text
    assert "字段 irreplaceability" in text
    assert "分级" in text
    assert len(text) <= 1200


def test_summary_truncates_on_request():
    text = summarize_for_model(context_with_layer(), max_chars=40)
    assert len(text) == 40 and text.endswith("…")
