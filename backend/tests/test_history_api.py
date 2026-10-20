import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from app import db, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, db_path=path))
    now = int(time.time())
    db.insert_samples(path, [{"ts": now - 60 + i, "cpu": 10.0 + i, "memory": 40.0} for i in range(30)])
    return TestClient(main.app)


def test_history_default_returns_all_metrics(client):
    body = client.get("/api/history").json()
    assert body["range"] == "1h"
    assert set(body["series"]) == set(db.METRICS)
    assert body["bucket_seconds"] == db.bucket_seconds(3600)
    assert body["series"]["cpu"] and body["series"]["cpu"][0][1] is not None
    assert all(v is None for _, v in body["series"]["temperature"])


def test_history_selected_metrics_and_range(client):
    body = client.get("/api/history", params={"metric": "cpu,memory", "range": "24h"}).json()
    assert set(body["series"]) == {"cpu", "memory"}
    assert body["range"] == "24h"
    assert body["since"] < time.time() - 86000


def test_history_rejects_unknown_metric(client):
    response = client.get("/api/history", params={"metric": "cpu;DROP TABLE metrics"})
    assert response.status_code == 400
    assert "unknown metric" in response.json()["detail"]


def test_history_rejects_bad_range(client):
    assert client.get("/api/history", params={"range": "30d"}).status_code == 400


def test_lifespan_starts_and_stops_sampler(tmp_path, monkeypatch):
    path = str(tmp_path / "life.db")
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, db_path=path, sample_interval=1, flush_interval=1))
    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200
    assert db.latest_ts(path) is not None  # shutdown flushed at least one sample
