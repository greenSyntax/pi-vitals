# Pi-Vitals — Implementation Plan

A self-hosted dashboard that runs **on the Raspberry Pi itself** and visualises its health: CPU, memory, storage, temperature/throttling, open ports and Nginx configuration.

## Assumptions (change if wrong)

- Raspberry Pi OS (Debian-based), Python 3.9+
- Nginx is installed on the Pi (or will be installed by `install.sh`)
- LAN-only access, protected by Nginx basic auth
- 7 days of metric history, sampled every 5 s and downsampled
- Read-only: the app never modifies Nginx or any system setting

## Design System

| Item | Choice |
|---|---|
| **Icons** | [Lucide](https://lucide.dev/icons/), vendored locally as inline SVG or a sprite (only the icons we use) |
| **Font** | [Google Sans](https://fonts.google.com/specimen/Google+Sans), self-hosted `woff2` (400/500/700) with `font-display: swap` and a system-font fallback stack. No runtime call to Google. |
| **Palette** | [Color Hunt palette](https://colorhunt.co/palette/09232812544f2a835f8bbb92) |

**Palette tokens** (CSS custom properties in `frontend/css/tokens.css`):

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#092328` | Page background |
| `--surface` | `#12544f` | Cards, panels, table headers |
| `--accent` | `#2a835f` | Primary actions, active tab, chart primary line, "healthy" state |
| `--accent-soft` | `#8bbb92` | Text highlights, secondary chart series, borders, icons on dark |

**Semantic status colours** (the palette has only greens, so these are added for warning and danger states):

| Token | Hex | Use |
|---|---|---|
| `--warn` | `#e0b04a` | Temp or usage nearing a threshold, throttling history |
| `--danger` | `#e5674f` | Over threshold, undervoltage, all-interface listeners, invalid Nginx config |

**Design rules**
- Dark-first theme built on `--bg` / `--surface`. A light theme is derived from the same tokens, not a second palette.
- Never rely on colour alone for status: pair it with a Lucide icon and a text label (for example `thermometer` + "72°C").
- Check text and chart contrast (WCAG AA) on `--surface`. `--accent` (`#2a835f`) is too dark for small text on `--bg`, so use `--accent-soft` for text and reserve `--accent` for fills and lines.
- Chart series colours come from the tokens above (accent, accent-soft, warn), so charts match the UI.
- Icons are Lucide at 20px/1.75 stroke, inheriting `currentColor`.
- Candidate icons: `cpu`, `memory-stick`, `hard-drive`, `thermometer`, `gauge`, `network`, `plug`, `shield-alert`, `server`, `activity`, `clock`, `triangle-alert`, `circle-check`, `refresh-cw`.

## Target Architecture

```
Collector (psutil) ──▶ SQLite ──▶ FastAPI (127.0.0.1:8000) ──▶ Nginx (:80, basic auth) ──▶ Browser
                                                                  └─ serves static dashboard
```

## Proposed Layout

```
pi-vitals/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app + routes
│   │   ├── config.py          # settings (env vars)
│   │   ├── db.py              # SQLite access + retention
│   │   ├── scheduler.py       # background sampling loop
│   │   └── collectors/
│   │       ├── system.py      # cpu, memory, uptime, load
│   │       ├── health.py      # temperature, throttling
│   │       ├── storage.py     # partitions, usage, io
│   │       ├── ports.py       # listening sockets
│   │       └── nginx.py       # config parsing, status
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── css/                   # tokens.css (palette), base, components
│   ├── fonts/                 # Google Sans woff2 (self-hosted)
│   ├── icons/                 # Lucide SVGs / sprite
│   └── js/                    # charts, api client, views
├── deploy/
│   ├── pi-vitals.service      # systemd unit
│   ├── nginx-pi-vitals.conf   # site config
│   ├── sudoers-pi-vitals      # narrow sudo rule for `nginx -T`
│   └── install.sh
├── PLAN.md
└── README.md
```

---

## Phase 0 — Project Setup

**Goal:** a runnable skeleton and a dev loop on the Mac.

- [x] Create the folder layout above
- [x] Python venv, `requirements.txt` (`fastapi`, `uvicorn`, `psutil`, `pytest`)
- [x] `.gitignore` (venv, `__pycache__`, `*.db`, `.env`)
- [x] Minimal FastAPI app with `GET /api/health` returning `{"status":"ok"}`
- [x] `config.py` reading env vars (port, DB path, sample interval, retention days)
- [x] README with dev run instructions

**Done when:** `uvicorn app.main:app` runs locally and `/api/health` responds.

---

## Phase 1 — Core Metric Collectors

**Goal:** accurate live metrics from the system, each behind its own module.

- [x] `system.py`: CPU % (total and per core), CPU frequency, load average, memory and swap, uptime
- [x] `health.py`: CPU temperature (`/sys/class/thermal/thermal_zone0/temp`), throttling via `vcgencmd get_throttled` (decode bit flags: undervoltage, throttled, freq-capped)
- [x] `storage.py`: per-mount usage (skip pseudo filesystems), disk I/O rates
- [x] Graceful fallbacks: on non-Pi hosts (the Mac) return `null` for Pi-only values so dev still works
- [x] `GET /api/live` aggregating all of the above
- [x] Unit tests with mocked `psutil` and sysfs reads

**Done when:** `/api/live` returns a complete JSON snapshot, and tests pass on the Mac and on the Pi.

---

## Phase 2 — Ports and Nginx Inspection

**Goal:** security-relevant visibility.

**Open ports**
- [x] `ports.py`: listening TCP/UDP sockets with port, protocol, bind address and process name/PID
- [x] Flag exposure: `0.0.0.0` / `::` (all interfaces) vs `127.0.0.1` (local only)
- [x] `GET /api/ports`

**Nginx**
- [x] `nginx.py`: service status (via systemd), `nginx -t` result, version
- [x] Parse effective config (`nginx -T`) into server blocks: `listen`, `server_name`, `root`, `proxy_pass`, SSL on/off, `location` blocks
- [x] Return raw config text with secrets and credentials redacted
- [x] `GET /api/nginx` (summary and parsed servers) and `GET /api/nginx/raw`
- [x] Handle: Nginx not installed, permission denied, invalid config
- [x] Tests using sample `nginx -T` fixtures

**Done when:** both endpoints return correct data on the Pi, and failure modes return clear error payloads (not 500s).

---

## Phase 3 — Persistence and History

**Goal:** charts over time without wearing out the SD card.

- [x] SQLite schema: `metrics(ts, cpu, mem, temp, disk_root, load1, ...)`
- [x] Background sampler (every 5 s) started with the app lifespan
- [x] Batch writes (for example flush every 30 s) and use WAL mode to reduce SD writes
- [x] Retention job (hourly): keep raw data for 24 h, downsample to 1-min averages for 7 days, purge the rest
- [x] `GET /api/history?metric=cpu&range=1h|6h|24h|7d` returning downsampled points
- [x] Tests for downsampling and retention

**Done when:** history survives restarts, DB size stays bounded, and range queries return in under 100 ms.

---

## Phase 4 — Dashboard UI

**Goal:** a clear, responsive single-page dashboard (works on phone).

- [x] Design foundations: `tokens.css` with the palette and status colours, self-hosted Google Sans, Lucide icon sprite
- [x] Layout: sticky header (nav tabs, status badge, theme toggle) plus card grid; hostname and uptime live in the System card
- [x] **Overview cards:** CPU, memory, temperature and storage tiles with meters and colour thresholds, per-core bars, storage per mount
- [x] **Throttling banner** shown when undervoltage or throttling is detected (red for active problems, amber for "since boot")
- [x] **History charts:** CPU, memory, temperature, load with a time-range selector (uPlot), hover/keyboard readout and a table view
- [x] **Ports tab:** sortable, filterable table; amber badge for all-interface listeners (exposed is not automatically wrong, so not red)
- [x] **Nginx tab:** status, config test result, server blocks, collapsible raw config viewer
- [x] Live polling every 5 s, paused while the browser tab is hidden; stale data is dimmed when offline
- [x] Dark and light theme from the same tokens, offline-safe (vendor JS libs, fonts and icons locally, no CDN dependency)
- [x] Loading, empty and error states for every panel (no skeletons: charts keep their last render, dimmed, while refetching)

**Done when:** all views work against the real API with sensible behaviour on mobile widths.
Verified on macOS at desktop and 375 px widths, in dark and light, against the real API plus a fixture-backed Nginx and faked throttling. Still to verify on the Pi.

---

## Phase 5 — Deployment on the Pi

**Goal:** one-command install, starts on boot.

- [ ] Dedicated system user `pivitals` (no login shell), added to groups needed for read access
- [ ] `pi-vitals.service` (systemd): runs uvicorn on `127.0.0.1:8000`, `Restart=always`, hardening options (`NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths` for the DB dir only)
- [ ] `sudoers-pi-vitals`: allow only `nginx -T` and `nginx -t` without a password
- [ ] `nginx-pi-vitals.conf`: serve `frontend/` statically, proxy `/api` to the backend, basic auth, security headers
- [ ] `install.sh`: install deps, create the venv, htpasswd prompt, install the unit and Nginx site, `nginx -t`, reload, enable and start the service
- [ ] Deploy flow documented: `rsync` or `git pull` over SSH, then restart

**Done when:** a reboot of the Pi brings the dashboard back at `http://pi.local` behind the login prompt.

---

## Phase 6 — Hardening and Verification

**Goal:** trust it and leave it running.

- [ ] Security pass: the backend isn't reachable except via Nginx, no write endpoints, redaction works, error messages don't leak paths
- [ ] Resource check: the app's own CPU and RAM stay low (target under 3% CPU, under 80 MB RAM on idle)
- [ ] Soak test: 24 h run, with no memory growth and DB within the size cap
- [ ] Failure drills: stop Nginx, break the config, fill the disk, unplug the temp sensor path, and confirm the UI degrades gracefully
- [ ] Log rotation and `journalctl` guidance

**Done when:** the soak test and failure drills pass.

---

## Phase 7 — Optional Enhancements (backlog)

- Alerts (email, Telegram or webhook) on high temperature, throttling, disk over 90%, or a new port opening
- Network throughput and per-interface stats
- Top processes by CPU and memory
- Systemd service status list
- Docker container overview
- Remote access via Tailscale
- Export metrics in Prometheus format
- HTTPS with a self-signed cert or mkcert

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| SD card wear from frequent writes | Batched writes, WAL, short retention, downsampling |
| `nginx -T` needs root | Narrow sudoers rule, only for that exact command |
| Process names for ports need elevated access | Group or capability grant, and degrade to port-only if denied |
| Exposing sensitive config | Basic auth, LAN-only, redaction, read-only API |
| Dev on Mac, run on Pi | Pi-only metrics return `null` on other hosts, tests use mocks |

## Order of Work

`Phase 0 → 1 → 2 → 3 → 4 → 5 → 6`. After Phase 4 you can already preview locally on the Mac, and Phase 5 is the first time it runs on the Pi.
