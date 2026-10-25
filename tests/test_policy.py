"""确认策略的纯函数测试。"""
from __future__ import annotations

import pytest

from geo_harness.policy import (
    DEFAULT_CONFIRM,
    PolicyError,
    bbox_area_m2,
    decide,
    normalize,
)


def test_normalize_fills_defaults():
    data = normalize(None)
    assert data == DEFAULT_CONFIRM
    assert data["extent_area_gt"] == 5.0e9 and data["raster_pixels_gt"] == 1.0e8


def test_normalize_accepts_overrides():
    data = normalize({"enabled": False, "actions": ["undo"], "extent_area_gt": 1.0e6})
    assert data["enabled"] is False
    assert data["actions"] == ["undo"]
    assert data["extent_area_gt"] == 1.0e6
    assert data["raster_pixels_gt"] == 1.0e8


def test_normalize_rejects_bad_values():
    with pytest.raises(PolicyError):
        normalize({"actions": ["teleport"]})
    with pytest.raises(PolicyError):
        normalize({"extent_area_gt": -1})
    with pytest.raises(PolicyError):
        normalize({"enabled": "yes"})
    with pytest.raises(PolicyError):
        normalize("nope")


def test_bbox_area_is_plausible_for_the_case():
    area = bbox_area_m2([89.7, -10.05, 140.8, 50.2])
    assert 1.0e13 < area < 1.0e14  # 约 3.6e13 m²


def test_bbox_area_rejects_bad_input():
    with pytest.raises(PolicyError):
        bbox_area_m2([1, 2, 3])


def test_decide_marks_listed_actions():
    result = decide("layer.remove", {"layer_id": "a"}, DEFAULT_CONFIRM)
    assert result["needs"] is True
    assert any("layer.remove" in reason for reason in result["reasons"])


def test_decide_marks_large_extent():
    result = decide("view.set", {"bbox": [89.7, -10.05, 140.8, 50.2]}, DEFAULT_CONFIRM)
    assert result["needs"] is True
    assert any("m²" in reason for reason in result["reasons"])


def test_decide_ignores_small_extent_and_plain_actions():
    small = [100.0, 30.0, 100.1, 30.1]  # 约 1e8 m²，低于 5e9
    assert decide("view.set", {"bbox": small}, DEFAULT_CONFIRM)["needs"] is False
    assert decide("layer.visibility", {"visible": False}, DEFAULT_CONFIRM)["needs"] is False


def test_decide_marks_many_pixels():
    result = decide("product.execute", {"raster_pixels": 2.0e8}, DEFAULT_CONFIRM)
    assert result["needs"] is True


def test_decide_respects_disabled_and_custom_thresholds():
    assert decide("layer.remove", {}, {"enabled": False})["needs"] is False
    custom = {"extent_area_gt": 1.0e15}
    assert decide("view.set", {"bbox": [89.7, -10.05, 140.8, 50.2]}, custom)["needs"] is False


def test_enforcement_only_gates_agents():
    from geo_harness.policy import enforcement

    assert enforcement("layer.remove", {"layer_id": "a"}, DEFAULT_CONFIRM, "ui") == []
    reasons = enforcement("layer.remove", {"layer_id": "a"}, DEFAULT_CONFIRM, "agent")
    assert reasons and "layer.remove" in reasons[0]


def test_enforcement_allows_explicit_confirm():
    from geo_harness.policy import enforcement

    assert (
        enforcement("layer.remove", {}, DEFAULT_CONFIRM, "agent", explicit_confirm=True)
        == []
    )


def test_enforcement_covers_extent_threshold_and_disabled_policy():
    from geo_harness.policy import enforcement

    big = {"bbox": [89.7, -10.05, 140.8, 50.2]}
    assert enforcement("view.set", big, DEFAULT_CONFIRM, "agent")
    small = {"bbox": [100.0, 30.0, 100.1, 30.1]}
    assert enforcement("view.set", small, DEFAULT_CONFIRM, "agent") == []
    assert enforcement("layer.remove", {}, {"enabled": False}, "agent") == []
