# CLAUDE.md

Guidance for Claude Code when working in this repo. Keep this file current: update it whenever commands, structure, conventions or decisions change (see "Maintaining docs").

## Project

**Pi-Vitals** is a self-hosted dashboard that runs on the Raspberry Pi itself. It monitors CPU, memory, storage, temperature/throttling, open ports and Nginx configuration, and shows them in a web UI with charts.

- Full roadmap: [PLAN.md](PLAN.md) (phased). Work phase by phase and tick the checklists as items land.
- Current phase: **Phases 0–3 done; Phase 4 (dashboard UI) next**. Phases 1–3 have only run on macOS: verify temperature/throttling, `/api/ports`, `/api/nginx` and history DB growth on the real Pi. Update this line as phases complete.

## Stack

- Backend: Python 3.9+, FastAPI, uvicorn, psutil, SQLite (WAL)
- Frontend: static HTML/CSS/JS, Chart.js or uPlot. No Node build step on the Pi.
- Serving: Nginx (static files, `/api` proxy, basic auth) and a `systemd` service
- Dev machine is macOS, target is Raspberry Pi OS (Debian)

## Layout

```
backend/app/        main.py (FastAPI routes + lifespan), config.py (env settings), db.py (SQLite), scheduler.py (Sampler thread)
backend/app/collectors/   system.py, health.py, storage.py, ports.py, nginx.py (each exposes collect())
backend/tests/      pytest (pytest.ini sets pythonpath to backend/)
frontend/           css/, fonts/, icons/, js/ (empty; index.html still to come)
deploy/             systemd unit, nginx site, sudoers rule, install.sh (empty so far)
```

Update this block as files are added. Env vars are listed in the README.

## Commands

Run from `backend/` (the venv is `backend/.venv`, git-ignored; system Python is 3.9, so keep code 3.9-compatible):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload     # dev server, http://127.0.0.1:8000
pytest                            # tests
```

## Conventions

- **Read-only app.** No endpoint may modify Nginx or any system setting. No write endpoints beyond internal DB writes.
- **Pi-only metrics degrade gracefully.** Temperature, `vcgencmd` throttling etc. return `null` on non-Pi hosts so development on macOS works. Collectors must never raise to the API layer: return an error payload instead.
- **One collector per module** under `collectors/`, exposing `collect() -> dict`, with unit tests that mock `psutil`, sysfs and subprocess output. `main.py` wraps each in `_safe()` so one failing collector returns `{"error": ...}` instead of breaking `/api/live`.
- **Nginx collector** (`nginx.py`): own brace-aware parser (tokenize → parse_config), not regexes. One `nginx -T` per 30 s is cached because sudo logs every call. Output is redacted (`redact()`, proxy_pass userinfo) before it leaves the collector; keep new fields that could carry secrets going through it. Sudo is opt-in via `PIVITALS_NGINX_USE_SUDO` and always `sudo -n` with a fixed binary path.
- **Ports collector** (`ports.py`): on macOS `psutil.net_connections` raises AccessDenied, so it falls back to per-process listing and sets `partial: true`. Same flag on Linux when some PIDs are hidden.
- psutil CPU percent is relative to the previous call, and that baseline is global: keep the priming call in `system.py`, and read CPU only through `_per_core_percent()` (it reuses a reading younger than 1 s so the history sampler and `/api/live` don't shrink each other's window). Don't call `psutil.cpu_percent` elsewhere.
- **History** (`db.py`, `scheduler.py`): a daemon `Sampler` thread (started in the FastAPI lifespan) samples every `PIVITALS_SAMPLE_INTERVAL` s into an in-memory buffer and flushes in one transaction every `PIVITALS_FLUSH_INTERVAL` s (and on shutdown). Hourly `db.maintain()` rolls raw rows older than 24 h into `metrics_1m` (1-min averages) and purges past retention. SQLite is WAL + `synchronous=NORMAL`. Each db function opens its own short-lived connection. API metric names map to columns via the `db.METRICS` whitelist: never put request input into SQL. Adding a metric means a new column in `COLUMNS` (existing DBs need a migration, since the schema is `CREATE TABLE IF NOT EXISTS`) plus `collect_sample`.
- **Protect the SD card.** Batch DB writes, use WAL, honour retention and downsampling. Don't add per-sample writes or verbose disk logging.
- **Security.** Backend binds to `127.0.0.1` only. Redact secrets in the Nginx config output. Shell out only with fixed argument lists (never `shell=True`, never user input in commands). The only sudo use is the narrow rule for `nginx -t` / `nginx -T`.
- **Offline-safe frontend.** Vendor JS libs, fonts and icons locally. No CDN or Google calls at runtime.
- Match the surrounding code's style, naming and comment density. Keep dependencies minimal: this runs on a Pi.

## Design system

- Icons: [Lucide](https://lucide.dev/icons/), inline SVG or sprite, 20px, 1.75 stroke, `currentColor`
- Font: Google Sans, self-hosted `woff2`, with a system-font fallback
- Palette: [Color Hunt](https://colorhunt.co/palette/09232812544f2a835f8bbb92)

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#092328` | Page background |
| `--surface` | `#12544f` | Cards, panels |
| `--accent` | `#2a835f` | Fills, buttons, chart lines, healthy state |
| `--accent-soft` | `#8bbb92` | Text, borders, icons |
| `--warn` | `#e0b04a` | Near-threshold (added, not in palette) |
| `--danger` | `#e5674f` | Over threshold / exposed / invalid (added, not in palette) |

Rules: dark-first; never rely on colour alone (pair with icon and label); use `--accent-soft` for small text, not `--accent` (contrast); define colours only as tokens in `frontend/css/tokens.css`.

## Maintaining docs

- **README.md** is for humans: what it is, how to run, install and deploy. **CLAUDE.md** is for Claude: conventions, constraints, decisions. **PLAN.md** is the roadmap.
- When a change affects commands, layout, endpoints, config/env vars, deployment or design tokens, update the relevant docs **in the same change**.
- When a phase item is done, tick it in PLAN.md and update "Current phase" above.
- Don't duplicate content across files: link instead.

## License

MIT ([LICENSE](LICENSE)), a deliberate choice. Only add dependencies with MIT-compatible licenses (no GPL/AGPL).

## Git

- Default branch: `main`. Commit only when asked.
