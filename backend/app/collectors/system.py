import os
import socket
import time
from typing import Optional

import psutil


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


# psutil reports usage since the previous call, and the first call returns 0.0.
# Prime it at import so the first real sample is meaningful.
psutil.cpu_percent(interval=None, percpu=True)


def collect() -> dict:
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    per_core = psutil.cpu_percent(interval=None, percpu=True)
    return {
        "hostname": socket.gethostname(),
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "cpu": {
            "percent": round(sum(per_core) / len(per_core), 1) if per_core else 0.0,
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
