from collections import namedtuple

import psutil

from app.collectors import storage

Part = namedtuple("Part", "device mountpoint fstype opts")
Usage = namedtuple("Usage", "total used free percent")


def test_pseudo_filesystems_skipped(monkeypatch):
    parts = [
        Part("/dev/root", "/", "ext4", ""),
        Part("tmpfs", "/run", "tmpfs", ""),
        Part("sysfs", "/sys", "sysfs", ""),
        Part("/dev/sda1", "/mnt/usb", "ext4", ""),
        Part("/dev/loop0", "/snap/core", "squashfs", ""),
    ]
    monkeypatch.setattr(psutil, "disk_partitions", lambda all=False: parts)
    monkeypatch.setattr(psutil, "disk_usage", lambda m: Usage(100, 40, 60, 40.0))
    mounts = [p["mountpoint"] for p in storage.collect()["partitions"]]
    assert mounts == ["/", "/mnt/usb"]


def test_unreadable_mount_skipped(monkeypatch):
    parts = [Part("/dev/root", "/", "ext4", ""), Part("/dev/sdb1", "/mnt/x", "ext4", "")]

    def usage(mount):
        if mount == "/mnt/x":
            raise PermissionError
        return Usage(100, 40, 60, 40.0)

    monkeypatch.setattr(psutil, "disk_partitions", lambda all=False: parts)
    monkeypatch.setattr(psutil, "disk_usage", usage)
    mounts = [p["mountpoint"] for p in storage.collect()["partitions"]]
    assert mounts == ["/"]


def test_io_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(psutil, "disk_partitions", lambda all=False: [])
    monkeypatch.setattr(psutil, "disk_io_counters", lambda: None)
    assert storage.collect()["io"] is None
