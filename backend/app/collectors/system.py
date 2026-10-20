import os
import socket
import threading
import time
from typing import List, Optional, Tuple

import psutil

# CPU usage is computed from deltas of psutil.cpu_times() against ONE global baseline.
# psutil.cpu_percent() is not used: recent psutil keeps its baseline per thread, so the first call
# in every new thread (our sampler, each web worker) returns a meaningless 0.0.
# A window much shorter than ~1 s is also unreliable, so shorter ones are never reported.
MIN_WINDOW = 1.5
_cpu_lock = threading.Lock()
_prev_times = psutil.cpu_times(percpu=True)
_baseline = time.monotonic()
_cpu_cache: List[float] = []


def _cpu_freq() -> Optional[dict]:
    try:
        freq = psutil.cpu_freq()
    except Exception:
        return None
    if freq is None:
        return None
    return {"current_mhz": round(freq.current, 1), "max_mhz": freq.max or None}


def _load_average() -> Optional[dict]:
    try:
        one, five, fifteen = os.getloadavg()
    except (AttributeError, OSError):
        return None
    return {"1m": round(one, 2), "5m": round(five, 2), "15m": round(fifteen, 2)}


def _busy_and_total(t) -> Tuple[float, float]:
    # Same accounting as psutil.cpu_percent: guest time is already inside user/nice, and
    # iowait counts as idle.
    total = sum(t) - getattr(t, "guest", 0) - getattr(t, "guest_nice", 0)
    idle = t.idle + getattr(t, "iowait", 0)
    return total - idle, total


def _per_core_percent() -> List[float]:
    """Per-core usage since the previous reading, shared by the history sampler and /api/live.

    Every caller moves the same baseline, so a call less than MIN_WINDOW after the last one gets
    the previous reading back instead; before any valid reading exists that is an empty list,
    which callers report as "no data" rather than a made-up 0%.
    """
    global _cpu_cache, _baseline, _prev_times
    with _cpu_lock:
        now = time.monotonic()
        if now - _baseline < MIN_WINDOW:
            return list(_cpu_cache)
        current = psutil.cpu_times(percpu=True)
        values = []
        for old, new in zip(_prev_times, current):
            busy_old, total_old = _busy_and_total(old)
            busy_new, total_new = _busy_and_total(new)
            delta = total_new - total_old
            values.append(round(max(0.0, min(100.0, (busy_new - busy_old) / delta * 100)), 1) if delta > 0 else 0.0)
        _prev_times, _baseline, _cpu_cache = current, now, values
        return list(values)


def collect() -> dict:
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    per_core = _per_core_percent()
    return {
        "hostname": socket.gethostname(),
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "cpu": {
            "percent": round(sum(per_core) / len(per_core), 1) if per_core else None,
            "per_core_percent": per_core,
            "cores": psutil.cpu_count(logical=True),
            "freq": _cpu_freq(),
            "load_avg": _load_average(),
        },
        "memory": {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "percent": mem.percent,
        },
        "swap": {
            "total": swap.total,
            "used": swap.used,
            "percent": swap.percent,
        },
    }
