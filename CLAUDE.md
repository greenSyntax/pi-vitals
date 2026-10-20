# CLAUDE.md

Guidance for Claude Code when working in this repo. Keep this file current: update it whenever commands, structure, conventions or decisions change (see "Maintaining docs").

## Project

**Pi-Vitals** is a self-hosted dashboard that runs on the Raspberry Pi itself. It monitors CPU, memory, storage, temperature/throttling, open ports and Nginx configuration, and shows them in a web UI with charts.

- Full roadmap: [PLAN.md](PLAN.md) (phased). Work phase by phase and tick the checklists as items land.
- Current phase: **Phases 0–5 written; Phase 6 (hardening and verification) next**. Everything so far has only run on macOS. The installer has never been run on a Pi: verify the install, `nginx -t`, the sudo rule, `vcgencmd`, temperature/throttling, `/api/ports`, `/api/nginx`, history DB growth, the UI and a reboot there. Update this line as phases complete.

## Stack

- Backend: Python 3.9+, FastAPI, uvicorn, psutil, SQLite (WAL)
- Frontend: static HTML/CSS + vanilla ES modules, uPlot for charts. No Node build step and no framework.
- Serving: Nginx (static files, `/api` proxy, basic auth) and a `systemd` service
- Dev machine is macOS, target is Raspberry Pi OS (Debian)

## Layout

```
backend/app/        main.py (FastAPI routes + lifespan), config.py (env settings), db.py (SQLite), scheduler.py (Sampler thread)
backend/app/collectors/   system.py, health.py, storage.py, ports.py, nginx.py (each exposes collect())
backend/tests/      pytest (pytest.ini sets pythonpath to backend/)
frontend/           index.html; css/ (tokens.css, base.css, components.css); js/ (app.js router+polling, charts.js, dom.js, format.js, api.js, theme.js, views/{overview,ports,nginx}.js); fonts/; icons/sprite.svg; vendor/uplot/; THIRD_PARTY.md
tools/              build_sprite.py (rebuilds icons/sprite.svg from Lucide SVGs)
deploy/             install.sh, uninstall.sh, pi-vitals.service, nginx-pi-vitals.conf, sudoers-pi-vitals, pi-vitals-process-names.conf (templates use @NAME@ placeholders filled in by install.sh `render`)
```

Update this block as files are added. Env vars are listed in the README.

## Commands

Run from `backend/` (the venv is `backend/.venv`, git-ignored; system Python is 3.9, so keep code 3.9-compatible):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # requirements.txt is runtime only (what the Pi installs)
uvicorn app.main:app --reload     # dev server, http://127.0.0.1:8000
pytest                            # tests
```

## Conventions

- **Read-only app.** No endpoint may modify Nginx or any system setting. No write endpoints beyond internal DB writes.
- **Pi-only metrics degrade gracefully.** Temperature, `vcgencmd` throttling etc. return `null` on non-Pi hosts so development on macOS works. Collectors must never raise to the API layer: return an error payload instead.
- **One collector per module** under `collectors/`, exposing `collect() -> dict`, with unit tests that mock `psutil`, sysfs and subprocess output. `main.py` wraps each in `_safe()` so one failing collector returns `{"error": ...}` instead of breaking `/api/live`.
- **Nginx collector** (`nginx.py`): own brace-aware parser (tokenize → parse_config), not regexes. One `nginx -T` per 30 s is cached because sudo logs every call. Output is redacted (`redact()`, proxy_pass userinfo) before it leaves the collector; keep new fields that could carry secrets going through it. Sudo is opt-in via `PIVITALS_NGINX_USE_SUDO` and always `sudo -n` with a fixed binary path.
- **Ports collector** (`ports.py`): on macOS `psutil.net_connections` raises AccessDenied, so it falls back to per-process listing and sets `partial: true`. Same flag on Linux when some PIDs are hidden.
- **CPU usage** (`system.py`): never use `psutil.cpu_percent()`. Recent psutil keeps its baseline per thread, so the first call in every new thread (our sampler, each web worker) returns a meaningless 0.0. CPU is computed from `psutil.cpu_times()` deltas against one lock-protected global baseline in `_per_core_percent()`. A call less than `MIN_WINDOW` (1.5 s) after the last one gets the previous reading, and before any valid reading exists the result is `None` / `[]` ("no data"), never a fake 0%. The first history sample therefore has a null CPU.
- **History** (`db.py`, `scheduler.py`): a daemon `Sampler` thread (started in the FastAPI lifespan) samples every `PIVITALS_SAMPLE_INTERVAL` s into an in-memory buffer and flushes in one transaction every `PIVITALS_FLUSH_INTERVAL` s (and on shutdown). Hourly `db.maintain()` rolls raw rows older than 24 h into `metrics_1m` (1-min averages) and purges past retention. SQLite is WAL + `synchronous=NORMAL`. Each db function opens its own short-lived connection. API metric names map to columns via the `db.METRICS` whitelist: never put request input into SQL. Adding a metric means a new column in `COLUMNS` (existing DBs need a migration, since the schema is `CREATE TABLE IF NOT EXISTS`) plus `collect_sample`.
- **Protect the SD card.** Batch DB writes, use WAL, honour retention and downsampling. Don't add per-sample writes or verbose disk logging.
- **Security.** Backend binds to `127.0.0.1` only. Redact secrets in the Nginx config output. Shell out only with fixed argument lists (never `shell=True`, never user input in commands). The only sudo use is the narrow rule for `nginx -t` / `nginx -T`.
- **Deploy files** (`deploy/`): templates are rendered by `install.sh`'s `render()` and checked by `tests/test_deploy.py` (rendering, the Nginx config parsed with our own parser, `visudo -cf`, systemd-option guards, port/binary consistency between files). Never run `install.sh` or `uninstall.sh` on the dev machine: they change the system (they refuse without root). Gotchas baked into the files: `NoNewPrivileges`/`RestrictSUIDSGID`/`CapabilityBoundingSet` break `sudo nginx -T`; `PrivateDevices` breaks `vcgencmd`; `add_header` inside an Nginx `location` drops all inherited headers (use `expires` there); `--no-access-log` keeps polling out of the journal; the sudoers rule and `PIVITALS_NGINX_BIN` use the same `@NGINX_BIN@`. Keep install.sh bash-3.2-sourceable (no bash 4 features) so tests can source it, and keep the `[ "${BASH_SOURCE[0]}" = "$0" ]` main guard.
- **Offline-safe frontend.** Vendor JS libs, fonts and icons locally. No CDN or Google calls at runtime. Third-party files and their licences are listed in `frontend/THIRD_PARTY.md`: update it when vendoring anything.
- **Frontend code.** Build DOM with `h()` from `js/dom.js` (strings become text nodes). Never use `innerHTML` or string-built HTML: process names, Nginx config and all API values are untrusted. Don't call native `node.append(null)` (it writes "null"); use `h()` or `append()` from `dom.js`. API URLs are relative (`api/live`) so the app also works behind a sub-path. Icons are `icon("name")`, and the name must exist in `icons/sprite.svg` (add it to the Lucide folder and run `tools/build_sprite.py`). Charts must have a table twin, a keyboard path and a no-data state. Poll only while the tab is visible.
- **Dev server serves the UI.** `main.py` mounts `frontend/` at `/` after the API routes (`PIVITALS_FRONTEND_DIR`, empty disables). In production Nginx serves the static files and proxies `/api`.
- Match the surrounding code's style, naming and comment density. Keep dependencies minimal: this runs on a Pi.

## Design system

- Icons: [Lucide](https://lucide.dev/icons/) via `icons/sprite.svg` (`<use>`), 18px (16 in controls), 1.75 stroke, `currentColor`
- Font: Google Sans, self-hosted `woff2`, with a system-font fallback
- Palette: [Color Hunt](https://colorhunt.co/palette/09232812544f2a835f8bbb92) `#092328` deep · `#12544f` teal · `#2a835f` green · `#8bbb92` sage. Neutrals are tinted steps between deep and sage (dark) or white (light), so both themes come from these four colours.
- All tokens live in `frontend/css/tokens.css` (colours, type scale `--fs-*`, spacing `--sp-*`, radii `--r-*`, `--control-h`). No colour, size or radius literals elsewhere; `grep` for hex/rgb outside tokens.css should find nothing.

Each colour has ONE meaning, the same in both themes:

| Role | Token | Dark | Light | Used for |
|---|---|---|---|---|
| Action | `--accent` | `#2a835f` | `#2a835f` | Brand mark, primary actions, active tab underline. Never data or status. |
| Data | `--data` (+ `--data-wash`) | `#8bbb92` | `#12544f` | Chart lines, meter and bar fills |
| Warning | `--warn` (+ `--warn-wash`) | `#e6b450` | `#9a6700` | "High" status only |
| Critical | `--danger` (+ `--danger-wash`) | `#f2627a` | `#d1246b` | "Critical" status only |
| Normal | (none) | neutral ink | neutral ink | Calm states stay uncoloured |
| Surfaces | `--bg`, `--surface`, `--surface-2`, `--border` | tinted deep teal | white / tinted | Page, cards, raised parts (table heads, meter tracks, active segment) |
| Text | `--text`, `--text-2`, `--text-3` | | | Primary, secondary, tertiary. All three are >= 4.5:1 on every surface: they are used for real reading text. |

Status is applied with `data-sev="ok|warn|danger|na"`, which sets `--sev-ink` (icon), `--sev-fill` (meter), `--sev-line` (border/stripe), `--sev-wash` (tint). Show status as `.status` (icon + word, in tiles and tables) or `.status-badge` / `.chip` (pills); never colour alone.

Rules and why:
- Dark-first, light from the same tokens (`data-theme` on `<html>`, falls back to the OS setting). Both light blocks in tokens.css must stay identical.
- Only one solid-accent element per view (the brand mark). Selected segments are neutral (`--surface-2`), the active tab is an underline, so nothing competes.
- Status pairs were checked with the dataviz validator: warn vs danger pass colour-blind separation in both themes. Data green vs critical red does not (deutan dE ~5) and cannot while data is the brand green, which is why status always carries an icon and a word.
- Verified 2026-10-21 with an in-browser audit of every visible text node on all three tabs in both themes: 0 failures, minimum 5.2:1 dark / 4.7:1 light. Re-run that kind of check after colour changes.
- Tiles are grids with `grid-template-columns: minmax(0, 1fr)`; an `auto` column grows to the width of nowrap text and pushes content out (this bit twice).
- Chart rules (from the dataviz guidance): one series per chart, no dual axes, 2px lines, hairline solid grid, 10% area wash, solid crosshair, value-first tooltip, single-line time ticks, direct "Latest" value in the card header instead of a legend box. Warn/danger thresholds live in `js/format.js`.

## Maintaining docs

- **README.md** is for humans: what it is, how to run, install and deploy. **CLAUDE.md** is for Claude: conventions, constraints, decisions. **PLAN.md** is the roadmap. **docs/how-pi-vitals-works.md** explains the architecture for a 10-year-old (kid word + grown-up word for every part, Mermaid diagram).
- When a change affects commands, layout, endpoints, config/env vars, deployment or design tokens, update the relevant docs **in the same change**.
- When a phase item is done, tick it in PLAN.md and update "Current phase" above.
- When components, data flow, security locks, file layout or numbers it quotes (5 s sampling, 30 s flush, 7-day retention, 256 MB cap) change, update `docs/how-pi-vitals-works.md` too, in the same plain style.
- Don't duplicate content across files: link instead.

## License

MIT ([LICENSE](LICENSE)), a deliberate choice. Only add dependencies with MIT-compatible licenses (no GPL/AGPL).

## Git

- Default branch: `main`. Commit only when asked.

## Naming

The repo, code and docs call the project **Pi-Vitals**; the name shown **in the UI** (title, header, Nginx auth realm) is **Pi Vitals** (no hyphen).
