from fastapi.testclient import TestClient

from app import main
from app.collectors import system

client = TestClient(main.app)


def test_live_snapshot_shape():
    body = client.get("/api/live").json()
    assert set(body) == {"timestamp", "system", "health", "storage"}
    assert 0 <= body["system"]["memory"]["percent"] <= 100
    assert body["system"]["cpu"]["cores"] >= 1
    assert body["system"]["uptime_seconds"] > 0
    assert "partitions" in body["storage"]
    # Pi-only values exist as keys even when unavailable (null off a Pi)
    assert "temperature_c" in body["health"]
    assert "throttling" in body["health"]


def test_cpu_reads_are_shared_within_a_second(monkeypatch):
    calls = []
    monkeypatch.setattr(system, "_cpu_cache", (0.0, []))
    monkeypatch.setattr(system.psutil, "cpu_percent", lambda **kw: calls.append(1) or [10.0, 30.0])
    first = system.collect()["cpu"]
    second = system.collect()["cpu"]
    assert len(calls) == 1
    assert first["percent"] == second["percent"] == 20.0


def test_failing_collector_is_isolated(monkeypatch):
    def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(system, "collect", boom)
    body = client.get("/api/live").json()
    assert body["system"] == {"error": "RuntimeError: nope"}
    assert "partitions" in body["storage"]
