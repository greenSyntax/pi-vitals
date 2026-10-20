# Pi-Vitals

A lightweight dashboard that runs on your Raspberry Pi and shows its health at a glance.

> **Status:** early development. Phases 0–5 (API, history, dashboard and the Pi installer) are written; the installer has not yet been run on a real Pi, so treat the first install as a test run. Hardening and a soak test come next. See [PLAN.md](PLAN.md) for the roadmap.

## What it monitors

- **Health:** CPU temperature, throttling and undervoltage flags, uptime, load
- **CPU:** total and per-core usage, frequency
- **Memory:** RAM and swap
- **Storage:** usage per mount, disk I/O
- **Open ports:** listening TCP/UDP sockets with owning process, flagging ports exposed on all interfaces
- **Nginx:** service status, config validity, parsed server blocks and the effective config

Live readings plus history charts (up to 7 days) are shown in a web dashboard with three tabs: **Overview** (CPU, memory, temperature and storage tiles, history charts with a table view, per-core bars, throttling alerts), **Ports** and **Nginx**. It has dark and light themes, works on a phone, and needs no internet access (fonts, icons and charts are bundled).

## How it works

```
Collector (psutil) → SQLite → FastAPI (127.0.0.1:8000) → Nginx (basic auth) → Browser
```

The app is read-only: it never changes Nginx or any system setting. The backend listens only on localhost, and Nginx serves the dashboard and proxies `/api`.

## Tech

Python + FastAPI + psutil, SQLite, static frontend (no build step), Nginx, `systemd`.
Design: [Lucide](https://lucide.dev/icons/) icons, Google Sans, [this palette](https://colorhunt.co/palette/09232812544f2a835f8bbb92), charts by [uPlot](https://github.com/leeoniya/uPlot). Bundled third-party files and licences: [frontend/THIRD_PARTY.md](frontend/THIRD_PARTY.md).

## Requirements

- Raspberry Pi running Raspberry Pi OS (or another Debian-based OS)
- Python 3.9+
- Nginx

## Development

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt     # runtime deps + pytest
uvicorn app.main:app --reload      # dashboard at http://127.0.0.1:8000/ , API at /api/...
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
| `PIVITALS_FRONTEND_DIR` | `../frontend` | Folder the dev server serves at `/`. Set to empty to serve only the API (production: Nginx serves the files). |
| `PIVITALS_NGINX_BIN` | auto-detected | Pin the `nginx` binary path. The installer sets it to the path the sudoers rule allows. |
| `PIVITALS_NGINX_USE_SUDO` | off | Run `nginx -t/-T/-v` via `sudo -n` (needs the sudoers rule from the deploy step). `nginx -T` usually needs root. |

## Deployment on the Pi

Tested statically on a Mac; not yet run on a real Pi (see [PLAN.md](PLAN.md), Phase 5).

**Install** (Raspberry Pi OS / Debian, as a user with `sudo`):

```bash
git clone <this repo> pi-vitals && cd pi-vitals
sudo ./deploy/install.sh
```

It asks you to choose a dashboard password, then installs Nginx and `python3-venv` if missing, copies the app to `/opt/pi-vitals`, creates a `pivitals` service user, installs the `systemd` service, a narrow sudoers rule and the Nginx site, and prints the URL. By default the dashboard is at `http://<pi>:8080/` (port 8080 so it never collides with your own sites on 80/443).

| Option | Meaning |
|---|---|
| `--port N` | Dashboard port (default 8080) |
| `--bind ADDR` | Bind address, e.g. the Pi's LAN IP to avoid listening on other interfaces |
| `--auth-user NAME` | Login name (default `admin`) |
| `--set-password` | Change the password on a re-run |
| `--process-names` | Let the Ports tab name processes owned by other users. This grants the service `CAP_SYS_PTRACE`, a powerful capability that allows inspecting any process, so it is off by default. |

**Upgrade:** `git pull && sudo ./deploy/install.sh` keeps your login and history. **Remove:** `sudo ./deploy/uninstall.sh` (add `--purge` to delete the history and the service user too). It never touches your other Nginx sites.

**How it is wired**

```
browser → Nginx :8080 (basic auth, static files, security headers) → /api → uvicorn 127.0.0.1:8000 → SQLite in /var/lib/pi-vitals
```

- The API runs as the unprivileged `pivitals` user and listens on localhost only. It can run exactly `sudo nginx -T` and `sudo nginx -v` (see `deploy/sudoers-pi-vitals`), which is how it reads the Nginx config.
- Settings can be overridden in `/etc/default/pi-vitals` (one `PIVITALS_...=value` per line, then `sudo systemctl restart pi-vitals`).
- Logs: `journalctl -u pi-vitals`. Status: `systemctl status pi-vitals`.

**Security notes**
- The login uses HTTP basic auth over plain HTTP, so the password crosses your network unencrypted. Keep it on a trusted LAN or behind a VPN such as Tailscale, and do not forward the port to the internet. HTTPS is on the backlog (Phase 7).
- The dashboard shows open ports and your Nginx config (secrets are redacted). Treat access to it as sensitive.

## Project docs

- [docs/how-pi-vitals-works.md](docs/how-pi-vitals-works.md): the system design and architecture, explained simply (with a diagram)
- [PLAN.md](PLAN.md): phased implementation plan
- [CLAUDE.md](CLAUDE.md): conventions and guidance for Claude Code

## License

[MIT](LICENSE)
