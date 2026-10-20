import time

from fastapi import FastAPI

from app.collectors import health, storage, system

app = FastAPI(title="Pi-Vitals", docs_url=None, redoc_url=None)


def _safe(collector) -> dict:
    """A failing collector must not take down the whole snapshot."""
    try:
        return collector.collect()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


@app.get("/api/health")
def api_health() -> dict:
    return {"status": "ok"}


@app.get("/api/live")
def api_live() -> dict:
    return {
        "timestamp": int(time.time()),
        "system": _safe(system),
        "health": _safe(health),
        "storage": _safe(storage),
    }
