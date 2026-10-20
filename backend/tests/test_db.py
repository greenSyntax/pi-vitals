import sqlite3
import time

import pytest

from app import db

NOW = 1_800_000_000  # multiple of 60


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "t.db")


def row(ts, **vals):
    return {"ts": ts, **vals}


def test_insert_and_query_roundtrip(path):
    bucket = db.bucket_seconds(3600)
    a, b = NOW - 600, NOW - 600 + 3 * bucket  # clearly in different buckets
    db.insert_samples(path, [row(a, cpu=10.0, memory=50.0), row(b, cpu=20.0, memory=60.0)])
    series = db.query_history(path, ["cpu", "memory"], 3600, NOW)
    assert series["cpu"] == [[a // bucket * bucket, 10.0], [b // bucket * bucket, 20.0]]
    assert [v for _, v in series["memory"]] == [50.0, 60.0]


def test_bucket_averages_and_nulls(path):
    bucket = db.bucket_seconds(3600)  # 12s
    start = (NOW - 600) // bucket * bucket
    db.insert_samples(path, [
        row(start, cpu=10.0, temperature=None),
        row(start + 5, cpu=30.0, temperature=None),
        row(start + bucket, cpu=50.0, temperature=60.0),
    ])
    series = db.query_history(path, ["cpu", "temperature"], 3600, NOW)
    assert series["cpu"] == [[start, 20.0], [start + bucket, 50.0]]
    assert series["temperature"] == [[start, None], [start + bucket, 60.0]]


def test_same_second_replaces(path):
    db.insert_samples(path, [row(NOW - 10, cpu=1.0)])
    db.insert_samples(path, [row(NOW - 10, cpu=9.0)])
    assert db.query_history(path, ["cpu"], 3600, NOW)["cpu"][0][1] == 9.0


def test_range_excludes_older_rows(path):
    db.insert_samples(path, [row(NOW - 7200, cpu=99.0), row(NOW - 60, cpu=1.0)])
    series = db.query_history(path, ["cpu"], 3600, NOW)["cpu"]
    assert [v for _, v in series] == [1.0]


def test_maintain_rolls_up_and_purges(path):
    old = NOW - 3 * 86400
    recent = NOW - 600
    db.insert_samples(path, [
        row(NOW - 2 * 86400 + 0, cpu=10.0),   # same minute -> averaged
        row(NOW - 2 * 86400 + 5, cpu=30.0),
        row(old - 9 * 86400, cpu=77.0),       # past 7d retention -> purged
        row(recent, cpu=5.0),                 # fresh -> stays raw
    ])
    db.maintain(path, NOW, retention_days=7)

    with sqlite3.connect(path) as conn:
        raw = [r[0] for r in conn.execute("SELECT ts FROM metrics")]
        minute = conn.execute("SELECT ts, cpu FROM metrics_1m").fetchall()
    assert raw == [recent]
    assert minute == [((NOW - 2 * 86400) // 60 * 60, 20.0)]

    # idempotent
    db.maintain(path, NOW, retention_days=7)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM metrics_1m").fetchone()[0] == 1


def test_query_spans_raw_and_rolled_up(path):
    db.insert_samples(path, [row(NOW - 3 * 86400, cpu=40.0), row(NOW - 60, cpu=10.0)])
    db.maintain(path, NOW, retention_days=7)
    series = db.query_history(path, ["cpu"], 7 * 86400, NOW)["cpu"]
    assert [v for _, v in series] == [40.0, 10.0]


def test_data_survives_reopen(path):
    db.insert_samples(path, [row(NOW - 10, cpu=3.0)])
    assert db.latest_ts(path) == NOW - 10
    assert db.query_history(path, ["cpu"], 3600, NOW)["cpu"][0][1] == 3.0


def test_wal_mode(path):
    with db.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_bucket_sizes_cap_points():
    for seconds in db.RANGES.values():
        assert seconds / db.bucket_seconds(seconds) <= db.MAX_POINTS


def test_week_of_data_queries_fast(path):
    """7d of 1-min rows plus 24h of 5s rows, as on a Pi after a week."""
    now = int(time.time()) // 60 * 60
    minute_rows = [row(now - 86400 - i * 60, cpu=i % 100, memory=50.0) for i in range(6 * 24 * 60)]
    raw_rows = [row(now - i * 5, cpu=i % 100, memory=50.0) for i in range(17280)]
    db.insert_samples(path, minute_rows + raw_rows)
    # move the minute rows into metrics_1m the way production does
    db.maintain(path, now, retention_days=7)

    for name, seconds in db.RANGES.items():
        started = time.perf_counter()
        series = db.query_history(path, list(db.METRICS), seconds, now)
        elapsed = time.perf_counter() - started
        assert len(series["cpu"]) <= db.MAX_POINTS + 1, name
        assert elapsed < 0.5, f"{name} took {elapsed:.3f}s"
