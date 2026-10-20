import sqlite3

import pytest

from app import db, scheduler
from app.scheduler import Sampler


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "t.db")


def count(path, table="metrics"):
    with sqlite3.connect(path) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def make(path, clock, sample_fn=None, **kw):
    return Sampler(
        path, interval=5, flush_interval=30, retention_days=7,
        sample_fn=sample_fn or (lambda: {"ts": int(clock()), "cpu": 1.0}), clock=clock, **kw,
    )


def test_writes_are_batched(path):
    clock = Clock()
    sampler = make(path, clock)
    for _ in range(5):
        clock.now += 5
        sampler.tick()
    assert count(path) == 0  # buffered, nothing hit the disk yet

    clock.now += 10  # 35s since start: flush is due
    sampler.tick()
    assert count(path) == 6


def test_stop_flushes_remaining(path):
    clock = Clock()
    sampler = make(path, clock)
    clock.now += 5
    sampler.tick()
    sampler.stop()
    assert count(path) == 1


def test_failing_sample_does_not_raise_or_stop(path):
    clock = Clock()
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("sensor gone")
        return {"ts": int(clock()), "cpu": 2.0}

    sampler = make(path, clock, sample_fn=flaky)
    sampler.tick()
    clock.now += 40
    sampler.tick()
    assert count(path) == 1


def test_failed_flush_keeps_samples(path, monkeypatch):
    clock = Clock()
    sampler = make(path, clock)
    real = db.insert_samples
    monkeypatch.setattr(db, "insert_samples", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    clock.now += 40
    sampler.tick()
    assert len(sampler._buffer) == 1

    monkeypatch.setattr(db, "insert_samples", real)
    clock.now += 40
    sampler.tick()
    assert count(path) == 2


def test_maintenance_runs_on_first_tick_then_hourly(path, monkeypatch):
    clock = Clock()
    sampler = make(path, clock)
    runs = []
    monkeypatch.setattr(db, "maintain", lambda *a: runs.append(a))
    sampler.tick()
    clock.now += 60
    sampler.tick()
    assert len(runs) == 1
    clock.now += scheduler.MAINTENANCE_INTERVAL
    sampler.tick()
    assert len(runs) == 2


def test_thread_start_stop(path):
    sampler = Sampler(path, interval=1, flush_interval=1, retention_days=7,
                      sample_fn=lambda: {"ts": 1_800_000_000, "cpu": 1.0})
    sampler.start()
    sampler.stop()
    assert count(path) >= 1


def test_collect_sample_fields():
    sample = scheduler.collect_sample(now=1234)
    assert sample["ts"] == 1234
    assert set(sample) == {"ts", "cpu", "memory", "swap", "temperature", "disk", "load1"}
    assert 0 <= sample["memory"] <= 100


def test_collect_sample_survives_collector_failures(monkeypatch):
    def boom():
        raise RuntimeError

    monkeypatch.setattr(scheduler.system, "collect", boom)
    monkeypatch.setattr(scheduler.health, "collect", boom)
    sample = scheduler.collect_sample(now=1)
    assert sample["cpu"] is None and sample["temperature"] is None
    assert sample["disk"] is not None
