"""Static checks of the deploy/ files. They can't prove an install works on a Pi, but they catch
broken templates, a config that fails to parse, and the settings that silently break features."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.collectors import nginx

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
FRONTEND = ROOT / "frontend"

RENDER_ENV = (
    "PREFIX=/opt/pi-vitals SVC_USER=pivitals PORT=8080 BIND=0.0.0.0 "
    "HTPASSWD=/etc/nginx/pi-vitals.htpasswd NGINX_BIN=/usr/sbin/nginx"
)


def render(name: str) -> str:
    """Render a deploy template exactly as install.sh does, by sourcing the real function."""
    script = f"source {DEPLOY / 'install.sh'}; {RENDER_ENV}; render {DEPLOY / name}"
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout


def active_lines(text: str):
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


# --- templates -------------------------------------------------------------

@pytest.mark.parametrize("name", ["pi-vitals.service", "sudoers-pi-vitals", "nginx-pi-vitals.conf"])
def test_no_placeholder_left_after_rendering(name):
    assert not re.findall(r"@[A-Z_]+@", render(name))


# --- nginx site ------------------------------------------------------------

def nginx_server():
    tree = nginx.parse_config(render("nginx-pi-vitals.conf"))
    (_, server), = nginx._find_servers(tree)
    return tree, server


def test_nginx_site_parses_and_has_expected_shape():
    tree, server = nginx_server()
    summary = nginx.summarize_server("http", server)
    assert [(l["address"], l["port"]) for l in summary["listen"]] == [("0.0.0.0", 8080)]
    assert summary["root"] == "/opt/pi-vitals/frontend"
    api = next(l for l in summary["locations"] if l["path"] == "/api/")
    assert api["proxy_pass"] == "http://127.0.0.1:8000"
    assert any(s["name"] == "limit_req_zone" for s in tree)  # http-level, so before the server block


def test_nginx_site_requires_login_and_hides_version():
    _, server = nginx_server()
    names = {s["name"]: s["args"] for s in server["block"] if s["block"] is None}
    assert names["auth_basic"] == ["Pi Vitals"]
    assert names["auth_basic_user_file"] == ["/etc/nginx/pi-vitals.htpasswd"]
    assert names["server_tokens"] == ["off"]


def test_nginx_locations_do_not_reset_security_headers():
    """add_header in a location drops every add_header inherited from the server block."""
    _, server = nginx_server()
    for loc in (s for s in server["block"] if s["name"] == "location"):
        assert not [s for s in loc["block"] if s["name"] == "add_header"], loc["args"]


def test_nginx_only_allows_reads():
    _, server = nginx_server()
    for loc in (s for s in server["block"] if s["name"] == "location" and s["args"] in (["/api/"], ["/"])):
        assert any(s["name"] == "limit_except" and s["args"] == ["GET", "HEAD"] for s in loc["block"])


def test_security_headers_present_and_csp_blocks_inline_script():
    _, server = nginx_server()
    headers = {s["args"][0]: s["args"][1] for s in server["block"] if s["name"] == "add_header"}
    assert {"Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"} <= set(headers)
    script_src = re.search(r"script-src ([^;]*)", headers["Content-Security-Policy"]).group(1)
    assert script_src == "'self'"


# --- systemd unit ----------------------------------------------------------

def test_service_unit_essentials():
    unit = render("pi-vitals.service")
    lines = active_lines(unit)
    exec_start = next(l for l in lines if l.startswith("ExecStart="))
    assert "/opt/pi-vitals/venv/bin/uvicorn app.main:app" in exec_start
    assert "--no-access-log" in exec_start  # a journal line per poll would wear the SD card
    assert "User=pivitals" in lines
    assert "Restart=always" in lines
    assert "StateDirectory=pi-vitals" in lines
    assert "Environment=PIVITALS_HOST=127.0.0.1" in lines  # API stays on localhost
    assert "Environment=PIVITALS_NGINX_USE_SUDO=1" in lines


def test_service_unit_avoids_settings_that_break_features():
    unit = "\n".join(active_lines(render("pi-vitals.service")))
    for option in ("NoNewPrivileges", "RestrictSUIDSGID", "CapabilityBoundingSet", "PrivateDevices", "ProtectProc"):
        assert option not in unit, f"{option} breaks sudo, vcgencmd or process names"


def test_api_port_matches_between_unit_and_nginx():
    unit = render("pi-vitals.service")
    port = re.search(r"PIVITALS_PORT=(\d+)", unit).group(1)
    assert f"proxy_pass http://127.0.0.1:{port};" in render("nginx-pi-vitals.conf")


# --- sudoers ---------------------------------------------------------------

def test_sudoers_allows_exactly_two_fixed_commands():
    rules = active_lines(render("sudoers-pi-vitals"))
    assert rules == ["pivitals ALL=(root) NOPASSWD: /usr/sbin/nginx -T, /usr/sbin/nginx -v"]
    assert "*" not in rules[0] and "ALL" not in rules[0].split(":")[1]


def test_sudoers_binary_is_the_one_the_unit_pins():
    unit = render("pi-vitals.service")
    assert "Environment=PIVITALS_NGINX_BIN=/usr/sbin/nginx" in unit
    assert "/usr/sbin/nginx -T" in render("sudoers-pi-vitals")


@pytest.mark.skipif(shutil.which("visudo") is None, reason="visudo not installed")
def test_sudoers_passes_visudo(tmp_path):
    path = tmp_path / "pi-vitals"
    path.write_text(render("sudoers-pi-vitals"))
    result = subprocess.run(["visudo", "-cf", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout


# --- scripts ---------------------------------------------------------------

@pytest.mark.parametrize("script", ["install.sh", "uninstall.sh"])
def test_scripts_are_valid_bash_and_executable(script):
    path = DEPLOY / script
    assert path.stat().st_mode & 0o111, "not executable"
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    assert "set -euo pipefail" in path.read_text()


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
@pytest.mark.parametrize("script", ["install.sh", "uninstall.sh"])
def test_shellcheck(script):
    assert subprocess.run(["shellcheck", str(DEPLOY / script)]).returncode == 0


def run_install(*args):
    return subprocess.run(["bash", str(DEPLOY / "install.sh"), *args], capture_output=True, text=True)


def test_install_help_exits_cleanly():
    result = run_install("--help")
    assert result.returncode == 0
    assert "--process-names" in result.stdout


@pytest.mark.parametrize("args,message", [
    (["--port", "abc"], "must be a number"),
    (["--port", "0"], "between 1 and 65535"),
    (["--port", "8000"], "used by the backend API"),
    (["--auth-user", "bad:name"], "may only contain"),
    (["--bind", "not-an-ip"], "IPv4"),
    (["--frobnicate"], "unknown option"),
])
def test_install_rejects_bad_input_before_touching_anything(args, message):
    result = run_install(*args)
    assert result.returncode != 0
    assert message in result.stderr


# --- packaging / offline guarantees ---------------------------------------

def test_runtime_requirements_exclude_test_tools():
    runtime = (ROOT / "backend/requirements.txt").read_text()
    assert "pytest" not in runtime and "httpx" not in runtime
    assert "-r requirements.txt" in (ROOT / "backend/requirements-dev.txt").read_text()


def test_frontend_has_no_external_requests():
    """The dashboard must work offline and under a script-src 'self' CSP."""
    pattern = re.compile(r"""(?:src|href)=["']https?:|url\(\s*["']?https?:|@import|(?:fetch|import)\(\s*["'`]https?:""")
    for path in FRONTEND.rglob("*"):
        if path.suffix not in {".html", ".css", ".js"} or "vendor" in path.parts:
            continue
        assert not pattern.search(path.read_text()), path


def test_index_html_has_no_inline_script_or_handlers():
    html = (FRONTEND / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert not re.search(r"\son\w+\s*=", html)
