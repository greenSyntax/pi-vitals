import math
import sqlite3
from contextlib import closing
from typing import Dict, Iterable, List, Optional

# API metric name -> column. Only these names ever reach SQL.
METRICS = {
    "cpu": "cpu",
    "memory": "memory",
    "swap": "swap",
    "temperature": "temperature",
    "disk": "disk",
    "load": "load1",
}
COLUMNS = list(METRICS.values())

RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}
MAX_POINTS = 300
RAW_RETENTION_SECONDS = 24 * 3600

_COLS_DDL = ", ".join(f"{c} REAL" for c in COLUMNS)
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS metrics (ts INTEGER PRIMARY KEY, {_COLS_DDL});
CREATE TABLE IF NOT EXISTS metrics_1m (ts INTEGER PRIMARY KEY, {_COLS_DDL});
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    # WAL + NORMAL means far fewer fsyncs, which is what keeps SD card wear down.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def insert_samples(path: str, rows: Iterable[dict]) -> int:
    """Write a batch of {"ts": int, <metric column>: float|None} rows in one transaction."""
    data = [(r["ts"], *(r.get(c) for c in COLUMNS)) for r in rows]
    if not data:
        return 0
    placeholders = ", ".join("?" * (len(COLUMNS) + 1))
    with closing(connect(path)) as conn, conn:
        conn.executemany(f"INSERT OR REPLACE INTO metrics VALUES ({placeholders})", data)
    return len(data)


def maintain(path: str, now: int, retention_days: int) -> None:
    """Roll raw samples older than 24h into 1-minute averages, then purge past retention."""
    raw_keep = min(RAW_RETENTION_SECONDS, retention_days * 86400)
    cutoff = (now - raw_keep) // 60 * 60  # minute-aligned, so a bucket is never rolled up half-full
    avgs = ", ".join(f"avg({c})" for c in COLUMNS)
    with closing(connect(path)) as conn, conn:
        conn.execute(
            f"INSERT OR REPLACE INTO metrics_1m "
            f"SELECT (ts / 60) * 60 AS bucket, {avgs} FROM metrics WHERE ts < ? GROUP BY bucket",
            (cutoff,),
        )
        conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM metrics_1m WHERE ts < ?", (now - retention_days * 86400,))


def bucket_seconds(range_seconds: int) -> int:
    return max(1, math.ceil(range_seconds / MAX_POINTS))


def query_history(path: str, metrics: List[str], range_seconds: int, now: int) -> Dict[str, list]:
    """Downsampled series: {metric: [[bucket_start_ts, avg|None], ...]} oldest first."""
    bucket = bucket_seconds(range_seconds)
    since = now - range_seconds
    cols = [METRICS[m] for m in metrics]
    select_cols = ", ".join(cols)
    avgs = ", ".join(f"avg({c})" for c in cols)
    sql = (
        f"SELECT (ts / ?) * ? AS t, {avgs} FROM ("
        f"SELECT ts, {select_cols} FROM metrics WHERE ts >= ? "
        f"UNION ALL SELECT ts, {select_cols} FROM metrics_1m WHERE ts >= ?"
        f") GROUP BY t ORDER BY t"
    )
    with closing(connect(path)) as conn:
        rows = conn.execute(sql, (bucket, bucket, since, since)).fetchall()
    series: Dict[str, list] = {m: [] for m in metrics}
    for row in rows:
        for name, value in zip(metrics, row[1:]):
            series[name].append([row[0], None if value is None else round(value, 1)])
    return series


def latest_ts(path: str) -> Optional[int]:
    with closing(connect(path)) as conn:
        row = conn.execute("SELECT max(ts) FROM metrics").fetchone()
    return row[0]
