import psutil

IGNORED_FSTYPES = {
    "tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs", "devfs",
    "autofs", "cgroup", "cgroup2", "efivarfs", "fusectl", "debugfs",
}
IGNORED_MOUNT_PREFIXES = ("/sys", "/proc", "/dev", "/run", "/snap")


def _is_real(part) -> bool:
    if part.fstype in IGNORED_FSTYPES:
        return False
    return not part.mountpoint.startswith(IGNORED_MOUNT_PREFIXES)


def _partitions() -> list:
    partitions = []
    for part in psutil.disk_partitions(all=False):
        if not _is_real(part):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        partitions.append({
            "device": part.device,
            "mountpoint": part.mountpoint,
            "fstype": part.fstype,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": usage.percent,
        })
    return partitions


def _io() -> dict:
    try:
        counters = psutil.disk_io_counters()
    except Exception:
        return None
    if counters is None:
        return None
    return {
        "read_bytes": counters.read_bytes,
        "write_bytes": counters.write_bytes,
        "read_count": counters.read_count,
        "write_count": counters.write_count,
    }


def collect() -> dict:
    return {"partitions": _partitions(), "io": _io()}
