import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_path: str
    sample_interval: int
    flush_interval: int
    retention_days: int
    nginx_use_sudo: bool


def load_settings() -> Settings:
    return Settings(
        host=os.getenv("PIVITALS_HOST", "127.0.0.1"),
        port=int(os.getenv("PIVITALS_PORT", "8000")),
        db_path=os.getenv("PIVITALS_DB_PATH", "pivitals.db"),
        sample_interval=int(os.getenv("PIVITALS_SAMPLE_INTERVAL", "5")),
        flush_interval=int(os.getenv("PIVITALS_FLUSH_INTERVAL", "30")),
        retention_days=int(os.getenv("PIVITALS_RETENTION_DAYS", "7")),
        nginx_use_sudo=os.getenv("PIVITALS_NGINX_USE_SUDO", "").lower() in ("1", "true", "yes"),
    )


settings = load_settings()
