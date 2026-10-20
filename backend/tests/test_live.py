import threading
from collections import namedtuple

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


Times = namedtuple("Times", "user nice system idle")
LinuxTimes = namedtuple("LinuxTimes", "user nice system idle iowait irq softirq steal guest guest_nice")


def fake_cpu(monkeypatch, before, after):
    """Baseline = `before`, next psutil.cpu_times() reading = `after`; baseline is old enough to be valid."""
    calls = []
    monkeypatch.setattr(system, "_prev_times", before)
    monkeypatch.setattr(system, "_baseline", -1000.0)
    monkeypatch.setattr(system, "_cpu_cache", [])
    monkeypatch.setattr(system.psutil, "cpu_times", lambda percpu=False: calls.append(1) or after)
    return calls


def test_cpu_percent_from_time_deltas(monkeypatch):
    fake_cpu(monkeypatch, [Times(0, 0, 0, 0), Times(0, 0, 0, 0)], [Times(30, 0, 10, 60), Times(0, 0, 0, 100)])
    cpu = system.collect()["cpu"]
    assert cpu["per_core_percent"] == [40.0, 0.0]
    assert cpu["percent"] == 20.0


def test_cpu_linux_fields_iowait_is_idle_and_guest_not_double_counted(monkeypatch):
    before = [LinuxTimes(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)]
    # 100 ticks: user 40 (of which guest 10), system 10, idle 30, iowait 20
    after = [LinuxTimes(40, 0, 10, 30, 20, 0, 0, 0, 10, 0)]
    fake_cpu(monkeypatch, before, after)
    assert system.collect()["cpu"]["per_core_percent"] == [50.0]  # busy 50 of 100


def test_cpu_reads_are_shared_within_the_window(monkeypatch):
    calls = fake_cpu(monkeypatch, [Times(0, 0, 0, 0)], [Times(50, 0, 0, 50)])
    first = system.collect()["cpu"]
    second = system.collect()["cpu"]
    assert len(calls) == 1
    assert first["percent"] == second["percent"] == 50.0


def test_cpu_window_too_short_reports_no_reading_not_zero(monkeypatch):
    calls = fake_cpu(monkeypatch, [Times(0, 0, 0, 0)], [Times(50, 0, 0, 50)])
    monkeypatch.setattr(system, "_baseline", system.time.monotonic())  # just set
    cpu = system.collect()["cpu"]
    assert calls == []
    assert cpu["percent"] is None
    assert cpu["per_core_percent"] == []


def test_cpu_reading_does_not_depend_on_the_calling_thread(monkeypatch):
    """psutil.cpu_percent() returns 0.0 on the first call in each new thread; we must not."""
    fake_cpu(monkeypatch, [Times(0, 0, 0, 0)], [Times(25, 0, 0, 75)])
    result = []
    worker = threading.Thread(target=lambda: result.append(system.collect()["cpu"]["percent"]))
    worker.start()
    worker.join()
    assert result == [25.0]


def test_cpu_zero_time_delta_is_zero_not_a_crash(monkeypatch):
    fake_cpu(monkeypatch, [Times(5, 0, 5, 5)], [Times(5, 0, 5, 5)])
    assert system.collect()["cpu"]["per_core_percent"] == [0.0]


def test_failing_collector_is_isolated(monkeypatch):
    def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(system, "collect", boom)
    body = client.get("/api/live").json()
    assert body["system"] == {"error": "RuntimeError: nope"}
    assert "partitions" in body["storage"]
