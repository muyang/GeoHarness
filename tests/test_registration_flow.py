"""注册向导端到端（官方 SDK 1.1.1.dev）：draft → submit → submissions。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

CARD = {
    "geocard_version": "1.0",
    "id": "local.test.dataset",
    "type": "data",
    "name": "本地测试数据集",
    "description": "用于端到端验证注册向导的合成条目。",
    "access": {"protocol": "https", "endpoint": "http://127.0.0.1:8787", "format": "GeoJSON"},
    "license": "Apache-2.0",
    "provenance": {"provider": "local-test"},
    "x-geonexus": {"revision": "2026-10-26T00:00:00Z"},
}


@pytest.fixture()
def client():
    from geo_harness.app import create_app

    client = TestClient(create_app(Path(tempfile.mkdtemp(prefix="gnx-register-"))))
    client.get("/")
    client.csrf = client.get("/api/session").json()["csrf"]
    return client


def test_draft_validate_submit_and_list(client):
    headers = {"X-Geo-CSRF": client.csrf}
    draft = client.post(
        "/api/register/draft",
        json={"metadata": CARD, "kind": "data", "node_url": "http://127.0.0.1:8787"},
        headers=headers,
    )
    assert draft.status_code == 200, draft.text
    body = draft.json()
    assert body["card"]["id"] == "local.test.dataset"
    assert body["binding"]["node_url"] == "http://127.0.0.1:8787"
    assert body["validation"]["valid"] is True, body["validation"]

    submitted = client.post("/api/register/submit", json=body, headers=headers)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "registered"

    listing = client.get("/api/register/submissions")
    assert listing.status_code == 200, listing.text
    entries = listing.json()["cards"]
    assert any(item["card"]["id"] == "local.test.dataset" for item in entries)
    assert listing.json()["count"] >= 1


def test_draft_rejects_unknown_kind(client):
    response = client.post(
        "/api/register/draft",
        json={"metadata": CARD, "kind": "galaxy"},
        headers={"X-Geo-CSRF": client.csrf},
    )
    assert response.status_code == 400
