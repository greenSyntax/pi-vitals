import logging
import threading
import time
from typing import Callable, List, Optional

from app import db
from app.collectors import health, storage, system

log = logging.getLogger("pivitals")

MAINTENANCE_INTERVAL = 3600


def _attempt(fn: Callable, default=None):
    try:
        return fn()
    except Exception:
        return default


def collect_sample(now: Optional[int] = None) -> dict:
    """One history row. A collector failing leaves its columns null rather than dropping the row."""
    sys_data = _attempt(system.collect, {})
    temp = _attempt(health.collect, {}).get("temperature_c")
    partitions = (_attempt(storage.collect, {}) or {}).get("partitions") or []
    root = next((p for p in partitions if p["mountpoint"] == "/"), partitions[0] if partitions else None)
    load = (sys_data.get("cpu") or {}).get("load_avg") or {}
    return {
        "ts": int(time.time()) if now is None else now,
        "cpu": (sys_data.get("cpu") or {}).get("percent"),
        "memory": (sys_data.get("memory") or {}).get("percent"),
        "swap": (sys_data.get("swap") or {}).get("percent"),
        "temperature": temp,
        "disk": root["percent"] if root else None,
        "load1": load.get("1m"),
    }


class Sampler:
    """Samples metrics on an interval and writes them to SQLite in batches.

    Samples are buffered in memory and flushed every `flush_interval` seconds so the
    SD card sees one small write per flush rather than one per sample.
    """

    def __init__(
        self,
        db_path: str,
        interval: int,
        flush_interval: int,
        retention_days: int,
        sample_fn: Callable[[], dict] = collect_sample,
        clock: Callable[[], float] = time.time,
    ):
        self.db_path = db_path
        self.interval = interval
        self.flush_interval = flush_interval
        self.retention_days = retention_days
        self.sample_fn = sample_fn
        self.clock = clock
        self._buffer: List[dict] = []
        self._last_flush = clock()
        self._last_maintenance: Optional[float] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def tick(self) -> None:
        """One iteration: sample, then flush and maintain when due. Never raises."""
        now = self.clock()
        try:
            self._buffer.append(self.sample_fn())
        except Exception:
            log.exception("sampling failed")
        if now - self._last_flush >= self.flush_interval:
            self.flush()
        if self._last_maintenance is None or now - self._last_maintenance >= MAINTENANCE_INTERVAL:
            self.maintain()

    def flush(self) -> None:
        if not self._buffer:
            self._last_flush = self.clock()
            return
        batch, self._buffer = self._buffer, []
        try:
            db.insert_samples(self.db_path, batch)
        except Exception:
            log.exception("flush failed; keeping %d samples", len(batch))
            self._buffer = batch + self._buffer
            self._buffer = self._buffer[-5000:]  # bound memory if the disk stays unwritable
        self._last_flush = self.clock()

    def maintain(self) -> None:
        self._last_maintenance = self.clock()
        try:
            db.maintain(self.db_path, int(self.clock()), self.retention_days)
        except Exception:
            log.exception("maintenance failed")

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="pivitals-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.flush()
