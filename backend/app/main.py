import mimetypes
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from app import db
from app.collectors import health, nginx, ports, storage, system
from app.config import settings
from app.scheduler import Sampler

mimetypes.add_type("font/woff2", ".woff2")  # missing from older Python mime tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    sampler = Sampler(
        settings.db_path, settings.sample_interval, settings.flush_interval, settings.retention_days
    )
    sampler.start()
    yield
    sampler.stop()


app = FastAPI(title="Pi-Vitals", docs_url=None, redoc_url=None, lifespan=lifespan)


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


@app.get("/api/history")
def api_history(metric: Optional[str] = None, range_: str = Query("1h", alias="range")) -> dict:
    names = metric.split(",") if metric else list(db.METRICS)
    unknown = [n for n in names if n not in db.METRICS]
    if unknown:
        raise HTTPException(400, f"unknown metric(s): {', '.join(unknown)}; valid: {', '.join(db.METRICS)}")
    if range_ not in db.RANGES:
        raise HTTPException(400, f"invalid range; valid: {', '.join(db.RANGES)}")

    seconds = db.RANGES[range_]
    now = int(time.time())

    def query() -> dict:
        return {
            "range": range_,
            "bucket_seconds": db.bucket_seconds(seconds),
            "since": now - seconds,
            "series": db.query_history(settings.db_path, names, seconds, now),
        }

    return _safe(query)


# Dev convenience: serve the dashboard from the same process. In production Nginx serves the
# static files and proxies /api here. Mounted last so it never shadows an API route.
if settings.frontend_dir and os.path.isdir(settings.frontend_dir):
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
