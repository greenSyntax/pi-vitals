# CLAUDE.md

Guidance for Claude Code when working in this repo. Keep this file current: update it whenever commands, structure, conventions or decisions change (see "Maintaining docs").

## Project

**Pi-Vitals** is a self-hosted dashboard that runs on the Raspberry Pi itself. It monitors CPU, memory, storage, temperature/throttling, open ports and Nginx configuration, and shows them in a web UI with charts.

- Full roadmap: [PLAN.md](PLAN.md) (phased). Work phase by phase and tick the checklists as items land.
- Current phase: **Phase 0 done; Phase 1 (core collectors) next**. Update this line as phases complete.

## Stack

- Backend: Python 3.9+, FastAPI, uvicorn, psutil, SQLite (WAL)
- Frontend: static HTML/CSS/JS, Chart.js or uPlot. No Node build step on the Pi.
- Serving: Nginx (static files, `/api` proxy, basic auth) and a `systemd` service
- Dev machine is macOS, target is Raspberry Pi OS (Debian)

## Layout

```
backend/app/        main.py (FastAPI), config.py (env settings); db, scheduler still to come
backend/app/collectors/   one module per metric group (empty so far)
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
- **One collector per module** under `collectors/`, with unit tests that mock `psutil`, sysfs and subprocess output.
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
