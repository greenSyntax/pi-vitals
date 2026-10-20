import time

from fastapi import FastAPI

from app.collectors import health, nginx, ports, storage, system

app = FastAPI(title="Pi-Vitals", docs_url=None, redoc_url=None)


def _safe(collect) -> dict:
    """A failing collector must not take down the whole snapshot."""
    try:
        return collect()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


@app.get("/api/health")
def api_health() -> dict:
    return {"status": "ok"}


@app.get("/api/live")
def api_live() -> dict:
    return {
        "timestamp": int(time.time()),
        "system": _safe(system.collect),
        "health": _safe(health.collect),
        "storage": _safe(storage.collect),
    }


@app.get("/api/ports")
def api_ports() -> dict:
    return _safe(ports.collect)


@app.get("/api/nginx")
def api_nginx() -> dict:
    return _safe(nginx.collect)


@app.get("/api/nginx/raw")
def api_nginx_raw() -> dict:
    return _safe(nginx.collect_raw)
