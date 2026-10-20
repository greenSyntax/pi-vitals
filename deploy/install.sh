#!/usr/bin/env bash
# Pi Vitals installer for Raspberry Pi OS / Debian.
#
#   sudo ./deploy/install.sh [options]
#
# Safe to re-run: it upgrades the app in place and keeps the existing login and history.
# See `--help`, and the "Deployment" section of the README.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PREFIX="${PIVITALS_PREFIX:-/opt/pi-vitals}"
SVC_USER="${PIVITALS_USER:-pivitals}"
PORT=8080
BIND=0.0.0.0
AUTH_USER=admin
PROCESS_NAMES=0
SET_PASSWORD=0

API_PORT=8000
HTPASSWD=/etc/nginx/pi-vitals.htpasswd
UNIT=/etc/systemd/system/pi-vitals.service
DROPIN_DIR=/etc/systemd/system/pi-vitals.service.d
SUDOERS=/etc/sudoers.d/pi-vitals
NGINX_BIN=""
NGINX_SITE=""

log() { printf '==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: sudo ./deploy/install.sh [options]

  --port N          Port Nginx listens on for the dashboard (default: $PORT)
  --bind ADDR       Address Nginx binds to (default: $BIND, all interfaces)
  --auth-user NAME  Dashboard login name (default: $AUTH_USER)
  --set-password    Ask for a new dashboard password even if one is already set
  --process-names   Let the Ports tab name processes owned by other users. Grants the
                    service CAP_SYS_PTRACE, a powerful capability: see the README.
  -h, --help        Show this help

Set PIVITALS_PASSWORD to give the password non-interactively (it is visible in the
environment of the install command, so prefer the prompt).
EOF
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --port) PORT="${2:?--port needs a value}"; shift 2 ;;
      --bind) BIND="${2:?--bind needs a value}"; shift 2 ;;
      --auth-user) AUTH_USER="${2:?--auth-user needs a value}"; shift 2 ;;
      --set-password) SET_PASSWORD=1; shift ;;
      --process-names) PROCESS_NAMES=1; shift ;;
      -h | --help) usage; exit 0 ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
  done
}

validate_inputs() {
  case "$PORT" in '' | *[!0-9]*) die "--port must be a number" ;; esac
  [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "--port must be between 1 and 65535"
  [ "$PORT" -ne "$API_PORT" ] || die "port $API_PORT is used by the backend API; choose another --port"
  printf '%s' "$AUTH_USER" | grep -Eq '^[A-Za-z0-9._-]+$' || die "--auth-user may only contain letters, digits, . _ -"
  printf '%s' "$BIND" | grep -Eq '^[0-9.]+$' || die "--bind must be an IPv4 address"
  printf '%s' "$PREFIX" | grep -Eq '^/[A-Za-z0-9._/-]+$' || die "PIVITALS_PREFIX must be an absolute path without spaces"
  printf '%s' "$SVC_USER" | grep -Eq '^[a-z_][a-z0-9_-]*$' || die "PIVITALS_USER is not a valid user name"
}

preflight() {
  [ "$(id -u)" -eq 0 ] || die "run as root: sudo ./deploy/install.sh"
  [ "$(uname -s)" = Linux ] || die "this installer is for Linux (Raspberry Pi OS / Debian)"
  command -v systemctl >/dev/null || die "systemd is required"
  command -v python3 >/dev/null || die "python3 is required"
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || die "Python 3.9 or newer is required"
  command -v openssl >/dev/null || die "openssl is required (used to hash the dashboard password)"
  [ -d "$SRC_DIR/backend/app" ] && [ -d "$SRC_DIR/frontend" ] || die "run this from a Pi Vitals checkout (missing backend/ or frontend/)"
}

install_packages() {
  local missing=""
  dpkg -s nginx >/dev/null 2>&1 || missing="$missing nginx"
  dpkg -s python3-venv >/dev/null 2>&1 || missing="$missing python3-venv"
  [ -z "$missing" ] && return 0
  command -v apt-get >/dev/null || die "missing packages ($missing) and apt-get is not available"
  log "installing:$missing"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $missing
}

ensure_user() {
  if id -u "$SVC_USER" >/dev/null 2>&1; then
    return 0
  fi
  log "creating system user $SVC_USER"
  useradd --system --user-group --home-dir /var/lib/pi-vitals --no-create-home \
    --shell /usr/sbin/nologin "$SVC_USER"
}

deploy_files() {
  log "copying the app to $PREFIX"
  install -d -m 0755 "$PREFIX"
  # Replace code, keep the venv
  rm -rf "$PREFIX/backend" "$PREFIX/frontend"
  tar -C "$SRC_DIR" \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='*.db*' \
    --exclude='.pytest_cache' --exclude='.DS_Store' --exclude='backend/tests' \
    -cf - backend frontend | tar -C "$PREFIX" -xf -
  chown -R root:root "$PREFIX"
  chmod -R a+rX "$PREFIX"
}

setup_venv() {
  if [ ! -x "$PREFIX/venv/bin/python" ]; then
    log "creating the Python virtualenv"
    python3 -m venv "$PREFIX/venv"
  fi
  log "installing Python dependencies"
  "$PREFIX/venv/bin/pip" install --quiet -r "$PREFIX/backend/requirements.txt"
}

# Fill the @PLACEHOLDERS@ of a deploy template and print the result.
render() {
  sed \
    -e "s|@PREFIX@|$PREFIX|g" \
    -e "s|@USER@|$SVC_USER|g" \
    -e "s|@PORT@|$PORT|g" \
    -e "s|@BIND@|$BIND|g" \
    -e "s|@HTPASSWD@|$HTPASSWD|g" \
    -e "s|@NGINX_BIN@|$NGINX_BIN|g" \
    "$1"
}

setup_password() {
  if [ -f "$HTPASSWD" ] && [ "$SET_PASSWORD" -ne 1 ] && [ -z "${PIVITALS_PASSWORD:-}" ]; then
    log "keeping the existing dashboard login (use --set-password to change it)"
    return 0
  fi
  local password="${PIVITALS_PASSWORD:-}" confirm
  if [ -z "$password" ]; then
    [ -t 0 ] || die "no terminal to ask for the dashboard password; set PIVITALS_PASSWORD"
    read -r -s -p "Choose a dashboard password for '$AUTH_USER' (8+ characters): " password; echo
    read -r -s -p "Repeat it: " confirm; echo
    [ "$password" = "$confirm" ] || die "passwords do not match"
  fi
  [ "${#password}" -ge 8 ] || die "the password must be at least 8 characters"

  local hash tmp group
  # Via stdin so the password never appears in a process list
  hash="$(printf '%s' "$password" | openssl passwd -apr1 -stdin)"
  password=""
  tmp="$(mktemp)"
  printf '%s:%s\n' "$AUTH_USER" "$hash" >"$tmp"
  group=root
  getent group www-data >/dev/null && group=www-data
  install -m 0640 -o root -g "$group" "$tmp" "$HTPASSWD"
  rm -f "$tmp"
  log "dashboard login saved for '$AUTH_USER'"
}

install_sudoers() {
  log "installing the sudoers rule for nginx -T"
  local tmp
  tmp="$(mktemp)"
  render "$SRC_DIR/deploy/sudoers-pi-vitals" >"$tmp"
  if ! visudo -cf "$tmp" >/dev/null; then
    rm -f "$tmp"
    die "the generated sudoers rule failed validation; nothing was installed"
  fi
  install -m 0440 -o root -g root "$tmp" "$SUDOERS"
  rm -f "$tmp"
}

install_service() {
  log "installing the systemd service"
  if getent group video >/dev/null; then
    render "$SRC_DIR/deploy/pi-vitals.service" >"$UNIT"
  else
    render "$SRC_DIR/deploy/pi-vitals.service" | grep -v '^SupplementaryGroups=video$' >"$UNIT"
  fi
  chmod 0644 "$UNIT"

  if [ "$PROCESS_NAMES" -eq 1 ]; then
    warn "--process-names grants the service CAP_SYS_PTRACE"
    install -d -m 0755 "$DROPIN_DIR"
    install -m 0644 "$SRC_DIR/deploy/pi-vitals-process-names.conf" "$DROPIN_DIR/process-names.conf"
  else
    rm -f "$DROPIN_DIR/process-names.conf"
    rmdir "$DROPIN_DIR" 2>/dev/null || true
  fi

  systemctl daemon-reload
  systemctl enable pi-vitals >/dev/null 2>&1
  systemctl restart pi-vitals
}

wait_for_api() {
  log "waiting for the API"
  local i
  for i in $(seq 1 20); do
    if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$API_PORT/api/health', timeout=2)" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  journalctl -u pi-vitals -n 30 --no-pager >&2 || true
  die "the API did not come up; see the log above (journalctl -u pi-vitals)"
}

install_nginx_site() {
  if [ -d /etc/nginx/sites-available ] && [ -d /etc/nginx/sites-enabled ]; then
    NGINX_SITE=/etc/nginx/sites-available/pi-vitals
  else
    NGINX_SITE=/etc/nginx/conf.d/pi-vitals.conf
  fi

  if [ ! -e "$NGINX_SITE" ] && command -v ss >/dev/null && [ -n "$(ss -H -ltn "( sport = :$PORT )" 2>/dev/null)" ]; then
    die "port $PORT is already in use; pick another one with --port"
  fi

  log "configuring Nginx on $BIND:$PORT"
  local backup=""
  if [ -e "$NGINX_SITE" ]; then
    backup="$(mktemp)"
    cp -p "$NGINX_SITE" "$backup"
  fi
  render "$SRC_DIR/deploy/nginx-pi-vitals.conf" >"$NGINX_SITE"
  if [ "$NGINX_SITE" = /etc/nginx/sites-available/pi-vitals ]; then
    ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/pi-vitals
  fi

  if ! nginx -t >/dev/null 2>&1; then
    nginx -t >&2 || true
    if [ -n "$backup" ]; then
      cp -p "$backup" "$NGINX_SITE"
    else
      rm -f "$NGINX_SITE" /etc/nginx/sites-enabled/pi-vitals
    fi
    [ -z "$backup" ] || rm -f "$backup"
    die "Nginx rejected the generated config; your previous config was restored"
  fi
  [ -z "$backup" ] || rm -f "$backup"

  if systemctl is-active --quiet nginx; then
    systemctl reload nginx
  else
    systemctl enable --now nginx >/dev/null 2>&1
  fi
}

summary() {
  local host ip url_port=""
  host="$(hostname)"
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [ "$PORT" -eq 80 ] || url_port=":$PORT"
  cat <<EOF

Pi Vitals is running.

  Open:      http://${ip:-$host}$url_port/   (or http://$host.local$url_port/)
  Login:     $AUTH_USER
  Service:   systemctl status pi-vitals     logs: journalctl -u pi-vitals
  Upgrade:   git pull && sudo ./deploy/install.sh
  Remove:    sudo ./deploy/uninstall.sh

The login is sent over plain HTTP, so keep this on a trusted LAN (or behind a VPN such as
Tailscale) and don't forward the port to the internet.
EOF
}

main() {
  parse_args "$@"
  validate_inputs
  preflight
  install_packages
  NGINX_BIN="$(readlink -f "$(command -v nginx)")"
  ensure_user
  deploy_files
  setup_venv
  setup_password
  install_sudoers
  install_service
  wait_for_api
  install_nginx_site
  summary
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
