import os
import re
import shutil
import subprocess
import time
from typing import List, Optional, Tuple

import psutil

from app.config import settings

BINARY_CANDIDATES = (
    "/usr/sbin/nginx",
    "/usr/local/sbin/nginx",
    "/usr/local/bin/nginx",
    "/opt/homebrew/bin/nginx",
)
COMMAND_TIMEOUT = 10
CACHE_TTL = 30  # `nginx -T` is not free and sudo logs every call, so don't run it per poll

_cache: dict = {}


# --- parsing ---------------------------------------------------------------

def tokenize(text: str) -> List[Tuple[str, str]]:
    """Split nginx config into ("op", ";{}") and ("word", ...) tokens, dropping comments."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "#":
            while i < n and text[i] != "\n":
                i += 1
        elif c in ";{}":
            tokens.append(("op", c))
            i += 1
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            tokens.append(("word", text[i + 1:j]))
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in ";}":
                if text[j] == "{":
                    if j > i and text[j - 1] == "$":  # ${var}
                        j = text.find("}", j) + 1 or n
                        continue
                    break
                j += 1
            tokens.append(("word", text[i:j]))
            i = j
    return tokens


def _parse_block(tokens: list, pos: int, depth: int) -> Tuple[list, int]:
    stmts = []
    args: List[str] = []
    while pos < len(tokens):
        kind, value = tokens[pos]
        pos += 1
        if kind == "word":
            args.append(value)
        elif value == ";":
            if args:
                stmts.append({"name": args[0], "args": args[1:], "block": None})
            args = []
        elif value == "{":
            block, pos = _parse_block(tokens, pos, depth + 1)
            stmts.append({"name": args[0] if args else "", "args": args[1:], "block": block})
            args = []
        else:  # "}"
            if depth == 0:
                raise ValueError("unbalanced '}'")
            return stmts, pos
    if depth > 0:
        raise ValueError("unclosed '{'")
    return stmts, pos


def parse_config(text: str) -> list:
    stmts, _ = _parse_block(tokenize(text), 0, 0)
    return stmts


def split_dump(dump: str) -> List[Tuple[str, str]]:
    """Split `nginx -T` output into (path, content) per config file."""
    parts = re.split(r"^# configuration file (.+?):[ \t]*$", dump, flags=re.MULTILINE)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def _find_servers(stmts: list, context: str = "http"):
    for stmt in stmts:
        if stmt["block"] is None:
            continue
        if stmt["name"] == "server":
            yield context, stmt
        elif stmt["name"] == "stream":
            yield from _find_servers(stmt["block"], "stream")
        elif stmt["name"] == "http":
            yield from _find_servers(stmt["block"], "http")


def _first(block: list, name: str) -> Optional[dict]:
    return next((s for s in block if s["name"] == name and s["block"] is None), None)


def parse_listen(args: List[str]) -> dict:
    target = args[0] if args else ""
    flags = args[1:]
    address: Optional[str] = None
    port: Optional[int] = None
    if target.startswith("unix:"):
        address = target
    elif target.startswith("["):
        end = target.find("]")
        address = target[1:end]
        if target[end + 1:].startswith(":") and target[end + 2:].isdigit():
            port = int(target[end + 2:])
    elif target.isdigit():
        port = int(target)
    elif ":" in target:
        host, _, p = target.rpartition(":")
        address = host
        port = int(p) if p.isdigit() else None
    elif target:
        address = target
    if port is None and address is not None and not address.startswith("unix:"):
        port = 80
    return {
        "raw": " ".join(args),
        "address": address,
        "port": port,
        "ssl": "ssl" in flags,
        "default_server": "default_server" in flags,
    }


def _strip_userinfo(url: str) -> str:
    return re.sub(r"(//)[^/@\s]+@", r"\1[REDACTED]@", url)


def summarize_server(context: str, server: dict, source: Optional[str] = None) -> dict:
    block = server["block"]
    listens = [parse_listen(s["args"]) for s in block if s["name"] == "listen" and s["block"] is None]
    names = [a for s in block if s["name"] == "server_name" and s["block"] is None for a in s["args"]]
    root = _first(block, "root")
    ret = _first(block, "return")

    locations = []
    for loc in block:
        if loc["name"] != "location" or loc["block"] is None:
            continue
        proxy = _first(loc["block"], "proxy_pass")
        loc_root = _first(loc["block"], "root")
        alias = _first(loc["block"], "alias")
        loc_ret = _first(loc["block"], "return")
        locations.append({
            "path": " ".join(loc["args"]),
            "proxy_pass": _strip_userinfo(" ".join(proxy["args"])) if proxy else None,
            "root": " ".join(loc_root["args"]) if loc_root else None,
            "alias": " ".join(alias["args"]) if alias else None,
            "return": " ".join(loc_ret["args"]) if loc_ret else None,
        })

    return {
        "context": context,
        "source": source,
        "listen": listens,
        "server_names": names,
        "root": " ".join(root["args"]) if root else None,
        "return": " ".join(ret["args"]) if ret else None,
        "ssl": any(l["ssl"] for l in listens) or _first(block, "ssl_certificate") is not None,
        "locations": locations,
    }


# --- redaction -------------------------------------------------------------

SENSITIVE_DIRECTIVES = {
    "ssl_certificate_key", "ssl_password_file", "ssl_session_ticket_key", "auth_basic_user_file",
}
SENSITIVE_PATTERN = re.compile(r"password|passwd|secret|token|api[_-]?key|authorization|private", re.I)
_DIRECTIVE_LINE = re.compile(r"^(\s*)(\w+)\s+(.*);\s*(#.*)?$")


def redact(text: str) -> str:
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            out.append(line)
            continue
        m = _DIRECTIVE_LINE.match(line)
        if m and (m.group(2) in SENSITIVE_DIRECTIVES or SENSITIVE_PATTERN.search(m.group(2) + " " + m.group(3))):
            out.append(f"{m.group(1)}{m.group(2)} [REDACTED];")
        else:
            out.append(_strip_userinfo(line))
    return "\n".join(out)


# --- running nginx ---------------------------------------------------------

def _find_binary() -> Optional[str]:
    if settings.nginx_bin:  # pinned, so it matches the path the sudoers rule allows
        return settings.nginx_bin if os.access(settings.nginx_bin, os.X_OK) else None
    found = shutil.which("nginx")
    if found:
        return found
    return next((p for p in BINARY_CANDIDATES if os.access(p, os.X_OK)), None)


def _run(args: List[str]) -> subprocess.CompletedProcess:
    cmd = ["sudo", "-n"] + args if settings.nginx_use_sudo else args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=COMMAND_TIMEOUT)


def _is_running() -> bool:
    for proc in psutil.process_iter(["name"]):
        if proc.info.get("name") == "nginx":
            return True
    return False


def _version(binary: str) -> Optional[str]:
    try:
        result = _run([binary, "-v"])
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"nginx/([\w.\-]+)", result.stderr + result.stdout)
    return m.group(1) if m else None


def _build_snapshot() -> dict:
    binary = _find_binary()
    if binary is None:
        return {"installed": False, "error": "not_installed"}

    snapshot = {"installed": True, "version": _version(binary), "error": None}
    try:
        result = _run([binary, "-T"])
    except subprocess.TimeoutExpired:
        return {**snapshot, "error": "timeout", "config_test": {"ok": False, "output": "nginx -T timed out"}}
    except (OSError, subprocess.SubprocessError) as exc:
        return {**snapshot, "error": "exec_failed", "config_test": {"ok": False, "output": str(exc)}}

    output = result.stderr.strip()
    snapshot["config_test"] = {"ok": result.returncode == 0, "output": output}
    if result.returncode != 0 and "permission denied" in output.lower():
        snapshot["error"] = "permission_denied"
    elif result.returncode != 0 and "password is required" in output.lower():
        snapshot["error"] = "sudo_not_permitted"

    servers, files, parse_errors = [], [], []
    for path, content in split_dump(result.stdout):
        files.append(path)
        try:
            tree = parse_config(content)
        except ValueError as exc:
            parse_errors.append({"file": path, "error": str(exc)})
            continue
        servers.extend(summarize_server(ctx, srv, path) for ctx, srv in _find_servers(tree))

    snapshot.update({
        "servers": servers,
        "files": files,
        "parse_errors": parse_errors,
        "raw": redact(result.stdout),
    })
    return snapshot


def _snapshot() -> dict:
    cached = _cache.get("snapshot")
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        return cached[1]
    snapshot = _build_snapshot()
    _cache["snapshot"] = (time.monotonic(), snapshot)
    return snapshot


def reset_cache() -> None:
    _cache.clear()


def collect() -> dict:
    snapshot = {k: v for k, v in _snapshot().items() if k != "raw"}
    snapshot["running"] = _is_running()
    return snapshot


def collect_raw() -> dict:
    snapshot = _snapshot()
    return {
        "installed": snapshot["installed"],
        "error": snapshot.get("error"),
        "raw": snapshot.get("raw"),
    }
