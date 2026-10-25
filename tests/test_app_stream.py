"""路由级：可续传 NDJSON 流（用假 chat，不调用模型）。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geo_harness import workbench as workbench_module


async def fake_chat(self, body, base_url, options=None):
    yield {"type": "token", "text": "甲"}
    yield {"type": "token", "text": "乙"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(workbench_module.Workbench, "chat", fake_chat)
    from geo_harness.app import create_app

    app = create_app(Path(tempfile.mkdtemp(prefix="gnx-stream-")))
    client = TestClient(app)
    client.get("/")  # establish the local session cookie
    client.csrf = client.get("/api/session").json()["csrf"]
    return client


def test_stream_assigns_sequence_and_resumes_without_rerun(client):
    payload = {"message": "你好", "stream_id": "s-fixed"}
    headers = {"X-Geo-CSRF": client.csrf}
    first = client.post("/api/workbench/chat/stream", json=payload, headers=headers)
    assert first.status_code == 200
    assert first.headers.get("X-Stream-Id") == "s-fixed"
    events = [json.loads(line) for line in first.text.strip().splitlines() if line.strip()]
    assert [event["seq"] for event in events] == [1, 2]

    resumed = client.post("/api/workbench/chat/stream", json=payload, headers={**headers, "X-Resume-From": "1"})
    assert resumed.status_code == 200
    tail = [json.loads(line) for line in resumed.text.strip().splitlines() if line.strip()]
    assert [event["seq"] for event in tail] == [2]
