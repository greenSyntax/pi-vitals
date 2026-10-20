import socket
from collections import namedtuple

import psutil

from app.collectors import ports

Addr = namedtuple("Addr", "ip port")
SConn = namedtuple("SConn", "fd family type laddr raddr status pid")
PConn = namedtuple("PConn", "fd family type laddr raddr status")

TCP, UDP = socket.SOCK_STREAM, socket.SOCK_DGRAM
V4, V6 = socket.AF_INET, socket.AF_INET6


def sconn(family, type_, ip, port, status, pid, remote=()):
    return SConn(-1, family, type_, Addr(ip, port), remote, status, pid)


class FakeProcess:
    names = {100: "nginx", 200: "sshd"}

    def __init__(self, pid):
        if pid not in self.names:
            raise psutil.NoSuchProcess(pid)
        self.pid = pid

    def name(self):
        return self.names[self.pid]


def test_exposure():
    assert ports.exposure("0.0.0.0") == "all_interfaces"
    assert ports.exposure("::") == "all_interfaces"
    assert ports.exposure("127.0.0.1") == "local"
    assert ports.exposure("::1") == "local"
    assert ports.exposure("192.168.1.5") == "specific"


def test_listeners_filtered_and_sorted(monkeypatch):
    conns = [
        sconn(V4, TCP, "0.0.0.0", 80, psutil.CONN_LISTEN, 100),
        sconn(V6, TCP, "::", 22, psutil.CONN_LISTEN, 200),
        sconn(V4, TCP, "127.0.0.1", 8000, psutil.CONN_LISTEN, 300),
        # established connection and connected UDP are not listeners
        sconn(V4, TCP, "10.0.0.2", 50000, psutil.CONN_ESTABLISHED, 200, remote=Addr("1.1.1.1", 443)),
        sconn(V4, UDP, "10.0.0.2", 40000, psutil.CONN_NONE, 200, remote=Addr("8.8.8.8", 53)),
        sconn(V4, UDP, "0.0.0.0", 5353, psutil.CONN_NONE, None),
        # unbound UDP socket (port 0)
        sconn(V4, UDP, "0.0.0.0", 0, psutil.CONN_NONE, 200),
        # duplicate entry
        sconn(V4, TCP, "0.0.0.0", 80, psutil.CONN_LISTEN, 100),
    ]
    monkeypatch.setattr(psutil, "net_connections", lambda kind="inet": conns)
    monkeypatch.setattr(psutil, "Process", FakeProcess)

    result = ports.collect()
    got = [(l["port"], l["protocol"], l["exposure"], l["process"]) for l in result["listeners"]]
    assert got == [
        (22, "tcp", "all_interfaces", "sshd"),
        (80, "tcp", "all_interfaces", "nginx"),
        (5353, "udp", "all_interfaces", None),
        (8000, "tcp", "local", None),  # pid 300 vanished
    ]
    assert result["listeners"][0]["ip_version"] == 6
    assert result["summary"] == {"total": 4, "all_interfaces": 3, "local_only": 1}
    assert result["partial"] is True  # the UDP listener has no pid


def test_complete_view_is_not_partial(monkeypatch):
    conns = [sconn(V4, TCP, "0.0.0.0", 80, psutil.CONN_LISTEN, 100)]
    monkeypatch.setattr(psutil, "net_connections", lambda kind="inet": conns)
    monkeypatch.setattr(psutil, "Process", FakeProcess)
    assert ports.collect()["partial"] is False


def test_access_denied_falls_back_to_own_processes(monkeypatch):
    class Proc:
        def __init__(self, pid, conns, deny=False):
            self.pid, self._conns, self._deny = pid, conns, deny

        def net_connections(self, kind="inet"):
            if self._deny:
                raise psutil.AccessDenied(self.pid)
            return self._conns

    def denied(kind="inet"):
        raise psutil.AccessDenied()

    procs = [
        Proc(100, [PConn(-1, V4, TCP, Addr("0.0.0.0", 80), (), psutil.CONN_LISTEN)]),
        Proc(1, [], deny=True),
    ]
    monkeypatch.setattr(psutil, "net_connections", denied)
    monkeypatch.setattr(psutil, "process_iter", lambda: procs)
    monkeypatch.setattr(psutil, "Process", FakeProcess)

    result = ports.collect()
    assert [(l["port"], l["pid"], l["process"]) for l in result["listeners"]] == [(80, 100, "nginx")]
    assert result["partial"] is True
