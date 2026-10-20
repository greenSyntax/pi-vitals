# Pi-Vitals

A lightweight dashboard that runs on your Raspberry Pi and shows its health at a glance.

> **Status:** early development. Phases 0–3 (skeleton, core metrics, open ports, Nginx inspection, history storage) are done; the dashboard UI is next. The API is complete, but there is no web UI yet. See [PLAN.md](PLAN.md) for the roadmap.

## What it monitors

- **Health:** CPU temperature, throttling and undervoltage flags, uptime, load
- **CPU:** total and per-core usage, frequency
- **Memory:** RAM and swap
- **Storage:** usage per mount, disk I/O
- **Open ports:** listening TCP/UDP sockets with owning process, flagging ports exposed on all interfaces
- **Nginx:** service status, config validity, parsed server blocks and the effective config

Live gauges plus history charts (up to 7 days) are served in a web UI.

## How it works

```
Collector (psutil) → SQLite → FastAPI (127.0.0.1:8000) → Nginx (basic auth) → Browser
```

The app is read-only: it never changes Nginx or any system setting. The backend listens only on localhost, and Nginx serves the dashboard and proxies `/api`.

## Tech

Python + FastAPI + psutil, SQLite, static frontend (no build step), Nginx, `systemd`.
Design: [Lucide](https://lucide.dev/icons/) icons, Google Sans, [this palette](https://colorhunt.co/palette/09232812544f2a835f8bbb92).

## Requirements

- Raspberry Pi running Raspberry Pi OS (or another Debian-based OS)
- Python 3.9+
- Nginx

## Development

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload      # http://127.0.0.1:8000/api/health
pytest                             # run tests
```

Pi-only metrics (temperature, throttling) show as unavailable when run on a non-Pi machine.

### API

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{"status":"ok"}` liveness check |
| `GET /api/live` | Snapshot: `system` (CPU, memory, swap, uptime, load), `health` (temperature, throttling flags), `storage` (partitions, disk I/O) |

| `GET /api/history?metric=cpu,memory&range=1h` | Downsampled history (≤ ~300 points per series). `metric`: any of `cpu`, `memory`, `swap`, `temperature`, `disk`, `load` (comma-separated; default all). `range`: `1h`, `6h`, `24h`, `7d` (default `1h`). Returns `series: {metric: [[unix_ts, value\|null], ...]}`. Invalid metric or range gives 400. |
| `GET /api/ports` | Listening TCP/UDP sockets: port, address, `exposure` (`all_interfaces` / `local` / `specific`), PID and process name, plus a summary. `partial: true` means some process info was hidden by permissions. |
| `GET /api/nginx` | `installed`, `running`, `version`, `config_test` (`nginx -t` result), parsed `servers` (listen, server names, root, SSL, locations with `proxy_pass`), `files`, `parse_errors`, and `error` (`not_installed`, `permission_denied`, `sudo_not_permitted`, `timeout`, `exec_failed`) |
| `GET /api/nginx/raw` | The effective config from `nginx -T`, with secrets redacted |

Try it: `curl http://127.0.0.1:8000/api/live`. Values that can't be read are `null`, and a failing collector returns `{"error": "..."}` for its section only.

### Configuration

Environment variables (all optional):

| Variable | Default | Meaning |
|---|---|---|
| `PIVITALS_HOST` | `127.0.0.1` | Bind address |
| `PIVITALS_PORT` | `8000` | Bind port |
| `PIVITALS_DB_PATH` | `pivitals.db` | SQLite file (relative to the working directory) |
| `PIVITALS_SAMPLE_INTERVAL` | `5` | Seconds between samples |
| `PIVITALS_FLUSH_INTERVAL` | `30` | Seconds between batched DB writes. Up to this much data can be lost on a crash or power cut; raise it to reduce SD card writes. |
| `PIVITALS_RETENTION_DAYS` | `7` | History kept |
| `PIVITALS_NGINX_USE_SUDO` | off | Run `nginx -t/-T/-v` via `sudo -n` (needs the sudoers rule from the deploy step). `nginx -T` usually needs root. |

## Deployment on the Pi

_Coming in Phase 5._ A single `deploy/install.sh` will set up the `systemd` service, the Nginx site with basic auth, and a low-privilege service user. The dashboard is intended for LAN access only.

## Project docs

- [PLAN.md](PLAN.md): phased implementation plan
- [CLAUDE.md](CLAUDE.md): conventions and guidance for Claude Code

## License

[MIT](LICENSE)
