"""freeze/replay 纯函数测试（不启动工作台）。"""

from __future__ import annotations

from geo_harness.workflows import compare_baseline, freeze_document, result_digest, signature

ROW = {
    "id": "plan-1",
    "name": "候选点筛选",
    "source": "agent",
    "steps": [
        {"id": "s1", "product_id": "p.a", "expected_digest": "sha:a", "arguments": {"x": 1}, "depends_on": []},
        {"id": "s2", "product_id": "p.b", "expected_digest": "sha:b", "arguments": {"y": {"$step": "s1", "path": "/result/z"}}, "depends_on": ["s1"]},
    ],
}
MODEL = {"id": "deepseek-v3", "params": {"temperature": 0.2}}
BASELINE = {"s1": {"status": "completed", "result_digest": "d1"}}


def test_freeze_document_is_self_describing_and_signed():
    document = freeze_document(ROW, MODEL, BASELINE)
    assert document["workflow_id"] == "plan-1" and document["source"] == "agent"
    assert [r["digest"] for r in document["resources"]] == ["sha:a", "sha:b"]
    assert document["model"]["id"] == "deepseek-v3"
    assert document["signature"] == signature(document)
    assert document["baseline"] == BASELINE


def test_signature_changes_when_any_field_changes():
    first = freeze_document(ROW, MODEL, BASELINE)
    changed = {**ROW, "name": "另一个名字"}
    second = freeze_document(changed, MODEL, BASELINE)
    assert first["signature"] != second["signature"]


def test_compare_baseline_reports_result_and_status_drift():
    same = {"s1": {"status": "completed", "result_digest": "d1"}}
    assert compare_baseline(BASELINE, same) == []
    changed = {"s1": {"status": "completed", "result_digest": "d2"}}
    assert compare_baseline(BASELINE, changed)[0]["reason"] == "result"
    failed = {"s1": {"status": "failed", "result_digest": None}}
    assert compare_baseline(BASELINE, failed)[0]["reason"] == "status"
    assert compare_baseline(BASELINE, {})[0]["reason"] == "missing"


def test_result_digest_is_stable_and_none_safe():
    value = {"b": 2, "a": [1, 2]}
    assert result_digest(value) == result_digest({"a": [1, 2], "b": 2})
    assert result_digest(None) is None
