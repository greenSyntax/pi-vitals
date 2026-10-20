import socket
from typing import Dict, List, Optional, Tuple

import psutil

ALL_INTERFACES = {"0.0.0.0", "::"}


def exposure(address: str) -> str:
    if address in ALL_INTERFACES:
        return "all_interfaces"
    if address.startswith("127.") or address == "::1":
        return "local"
    return "specific"


def _connections() -> Tuple[list, bool]:
    """Return (family, type, laddr, raddr, status, pid) tuples and whether we had to fall back.

    System-wide listing needs elevated rights on some platforms (macOS); fall back
    to walking our own processes, which gives a partial view.
    """
    try:
        return [
            (c.family, c.type, c.laddr, c.raddr, c.status, c.pid)
            for c in psutil.net_connections(kind="inet")
        ], False
    except psutil.AccessDenied:
        pass

    rows = []
    for proc in psutil.process_iter():
        getter = getattr(proc, "net_connections", None) or proc.connections
        try:
            for c in getter(kind="inet"):
                rows.append((c.family, c.type, c.laddr, c.raddr, c.status, proc.pid))
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return rows, True


def _process_name(pid: Optional[int], cache: Dict[int, Optional[str]]) -> Optional[str]:
    if pid is None:
        return None
    if pid not in cache:
        try:
            cache[pid] = psutil.Process(pid).name()
        except (psutil.Error, OSError):
            cache[pid] = None
    return cache[pid]


def collect() -> dict:
    rows, fallback = _connections()
    names: Dict[int, Optional[str]] = {}
    seen = set()
    listeners: List[dict] = []

    for family, sock_type, laddr, raddr, status, pid in rows:
        if not laddr or not laddr.port:  # port 0 is an unbound socket, not a listener
            continue
        if sock_type == socket.SOCK_STREAM and status == psutil.CONN_LISTEN:
            protocol = "tcp"
        elif sock_type == socket.SOCK_DGRAM and not raddr:
            protocol = "udp"
        else:
            continue

        key = (protocol, laddr.ip, laddr.port, pid)
        if key in seen:
            continue
        seen.add(key)

        listeners.append({
            "protocol": protocol,
            "address": laddr.ip,
            "port": laddr.port,
            "ip_version": 6 if family == socket.AF_INET6 else 4,
            "exposure": exposure(laddr.ip),
            "pid": pid,
            "process": _process_name(pid, names),
        })

    listeners.sort(key=lambda l: (l["port"], l["protocol"], l["address"]))
    return {
        "listeners": listeners,
        "partial": fallback or any(l["pid"] is None for l in listeners),
        "summary": {
            "total": len(listeners),
            "all_interfaces": sum(l["exposure"] == "all_interfaces" for l in listeners),
            "local_only": sum(l["exposure"] == "local" for l in listeners),
        },
    }
