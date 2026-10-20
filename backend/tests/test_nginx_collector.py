import dataclasses
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import main
from app.collectors import nginx

DUMP = r"""# configuration file /etc/nginx/nginx.conf:
user www-data;
events { worker_connections 768; }
http {
    # a comment with a { brace
    include /etc/nginx/sites-enabled/*;
    map $http_upgrade $connection_upgrade { default upgrade; '' close; }
    upstream backend { server 127.0.0.1:9000; }
}

# configuration file /etc/nginx/sites-enabled/default:
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    root /var/www/html;
    location / {
        try_files $uri $uri/ =404;
    }
}

# configuration file /etc/nginx/sites-enabled/app:
server {
    listen 443 ssl http2;
    listen 127.0.0.1:8443;
    server_name app.example.com www.example.com;
    ssl_certificate /etc/ssl/app.pem;
    ssl_certificate_key /etc/ssl/private/app.key;
    auth_basic "Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;
    location /api/ {
        proxy_pass http://admin:hunter2@127.0.0.1:8000;
        proxy_set_header Authorization "Bearer abc#123";
        proxy_set_header Host $host;
    }
    location ~ ^/static/(.*)$ {
        alias /srv/static/$1;
    }
    location /old { return 301 https://example.com/new; }
}
"""


@pytest.fixture(autouse=True)
def fresh_cache():
    nginx.reset_cache()
    yield
    nginx.reset_cache()


def done(returncode=0, stdout="", stderr=""):
    return lambda args: subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


# --- parser ----------------------------------------------------------------

def test_tokenize_skips_comments_keeps_quoted_specials():
    tokens = nginx.tokenize('a "x;y" b; # ignored { }\nc d;')
    assert tokens == [
        ("word", "a"), ("word", "x;y"), ("word", "b"), ("op", ";"),
        ("word", "c"), ("word", "d"), ("op", ";"),
    ]


def test_tokenize_variable_braces_are_not_blocks():
    assert nginx.tokenize("set $x ${host}_y;")[2] == ("word", "${host}_y")


def test_parse_nested_blocks():
    tree = nginx.parse_config("http { server { listen 80; location / { return 200; } } }")
    server = tree[0]["block"][0]
    assert server["name"] == "server"
    assert server["block"][0] == {"name": "listen", "args": ["80"], "block": None}
    assert server["block"][1]["name"] == "location"


@pytest.mark.parametrize("text", ["http {", "}", "http { server { }"])
def test_parse_unbalanced_raises(text):
    with pytest.raises(ValueError):
        nginx.parse_config(text)


@pytest.mark.parametrize("args,address,port,ssl,default", [
    (["80"], None, 80, False, False),
    (["443", "ssl", "http2"], None, 443, True, False),
    (["127.0.0.1:8080"], "127.0.0.1", 8080, False, False),
    (["[::]:80", "default_server"], "::", 80, False, True),
    (["*:81"], "*", 81, False, False),
    (["example.com"], "example.com", 80, False, False),
    (["unix:/run/x.sock"], "unix:/run/x.sock", None, False, False),
])
def test_parse_listen(args, address, port, ssl, default):
    got = nginx.parse_listen(args)
    assert (got["address"], got["port"], got["ssl"], got["default_server"]) == (address, port, ssl, default)


def test_split_dump_files():
    files = [path for path, _ in nginx.split_dump(DUMP)]
    assert files == [
        "/etc/nginx/nginx.conf",
        "/etc/nginx/sites-enabled/default",
        "/etc/nginx/sites-enabled/app",
    ]


# --- redaction -------------------------------------------------------------

def test_redact_secrets():
    out = nginx.redact(DUMP)
    assert "app.key" not in out
    assert ".htpasswd" not in out
    assert "hunter2" not in out
    assert "abc#123" not in out
    assert "ssl_certificate_key [REDACTED];" in out
    assert "proxy_set_header [REDACTED];" in out
    # harmless lines survive, and block openers that merely contain a keyword are untouched
    assert "proxy_set_header Host $host;" in out
    assert "ssl_certificate /etc/ssl/app.pem;" in out
    assert nginx.redact("location /api/token {") == "location /api/token {"
    assert "http://[REDACTED]@127.0.0.1:8000" in out


# --- collect ---------------------------------------------------------------

def patch_nginx(monkeypatch, run, binary="/usr/sbin/nginx"):
    monkeypatch.setattr(nginx, "_find_binary", lambda: binary)
    monkeypatch.setattr(nginx, "_run", run)
    monkeypatch.setattr(nginx, "_is_running", lambda: True)


def fake_run(args):
    if args[1] == "-v":
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="nginx version: nginx/1.22.1\n")
    return subprocess.CompletedProcess(
        args, 0, stdout=DUMP, stderr="nginx: configuration file /etc/nginx/nginx.conf test is successful\n"
    )


def test_collect_summarizes_servers(monkeypatch):
    patch_nginx(monkeypatch, fake_run)
    result = nginx.collect()

    assert result["installed"] and result["running"]
    assert result["version"] == "1.22.1"
    assert result["config_test"]["ok"] is True
    assert result["error"] is None
    assert "raw" not in result
    assert len(result["files"]) == 3
    assert result["parse_errors"] == []

    # `upstream { server ...; }` and `events` must not be mistaken for server blocks
    assert len(result["servers"]) == 2
    default, app = result["servers"]
    assert default["server_names"] == ["_"]
    assert default["root"] == "/var/www/html"
    assert default["ssl"] is False
    assert [l["port"] for l in default["listen"]] == [80, 80]

    assert app["ssl"] is True
    assert app["server_names"] == ["app.example.com", "www.example.com"]
    assert app["source"] == "/etc/nginx/sites-enabled/app"
    api, static, old = app["locations"]
    assert api["proxy_pass"] == "http://[REDACTED]@127.0.0.1:8000"
    assert static["path"] == "~ ^/static/(.*)$"
    assert static["alias"] == "/srv/static/$1"
    assert old["return"] == "301 https://example.com/new"


def test_collect_raw_is_redacted(monkeypatch):
    patch_nginx(monkeypatch, fake_run)
    result = nginx.collect_raw()
    assert "hunter2" not in result["raw"]
    assert "server_name app.example.com" in result["raw"]


def test_not_installed(monkeypatch):
    monkeypatch.setattr(nginx, "_find_binary", lambda: None)
    monkeypatch.setattr(nginx, "_is_running", lambda: False)
    result = nginx.collect()
    assert result["installed"] is False
    assert result["error"] == "not_installed"
    assert nginx.collect_raw()["raw"] is None


def test_permission_denied(monkeypatch):
    def run(args):
        if args[1] == "-v":
            return fake_run(args)
        return subprocess.CompletedProcess(
            args, 1, stdout="", stderr='nginx: [alert] could not open error log file: open() "/var/log/nginx/error.log" failed (13: Permission denied)'
        )

    patch_nginx(monkeypatch, run)
    result = nginx.collect()
    assert result["error"] == "permission_denied"
    assert result["config_test"]["ok"] is False
    assert result["servers"] == []


def test_invalid_config_reported(monkeypatch):
    def run(args):
        if args[1] == "-v":
            return fake_run(args)
        return subprocess.CompletedProcess(
            args, 1, stdout="", stderr='nginx: [emerg] unknown directive "foo" in /etc/nginx/nginx.conf:3'
        )

    patch_nginx(monkeypatch, run)
    result = nginx.collect()
    assert result["config_test"]["ok"] is False
    assert "unknown directive" in result["config_test"]["output"]
    assert result["error"] is None


def test_unparseable_file_is_isolated(monkeypatch):
    dump = "# configuration file /a.conf:\nhttp {\n\n# configuration file /b.conf:\nserver { listen 81; }\n"
    patch_nginx(monkeypatch, done(stdout=dump))
    result = nginx.collect()
    assert [e["file"] for e in result["parse_errors"]] == ["/a.conf"]
    assert [s["listen"][0]["port"] for s in result["servers"]] == [81]


def test_timeout_and_exec_errors(monkeypatch):
    def timeout(args):
        if args[1] == "-v":
            return fake_run(args)
        raise subprocess.TimeoutExpired(args, 10)

    patch_nginx(monkeypatch, timeout)
    assert nginx.collect()["error"] == "timeout"


def test_sudo_prefix(monkeypatch):
    calls = []
    monkeypatch.setattr(nginx.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr(nginx, "settings", dataclasses.replace(nginx.settings, nginx_use_sudo=True))
    nginx._run(["/usr/sbin/nginx", "-T"])
    assert calls == [["sudo", "-n", "/usr/sbin/nginx", "-T"]]


def test_result_is_cached(monkeypatch):
    count = {"n": 0}

    def run(args):
        count["n"] += 1
        return fake_run(args)

    patch_nginx(monkeypatch, run)
    nginx.collect()
    nginx.collect()
    nginx.collect_raw()
    assert count["n"] == 2  # one `-v` and one `-T`


def test_endpoints(monkeypatch):
    patch_nginx(monkeypatch, fake_run)
    client = TestClient(main.app)
    assert client.get("/api/nginx").json()["servers"][0]["server_names"] == ["_"]
    assert "raw" in client.get("/api/nginx/raw").json()
    assert "listeners" in client.get("/api/ports").json()
