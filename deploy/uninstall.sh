#!/usr/bin/env bash
# Removes Pi Vitals from this Pi.
#
#   sudo ./deploy/uninstall.sh [--purge]
#
# Keeps the history database and the service user unless --purge is given. It never touches
# the Nginx package or any of your other Nginx sites.
set -euo pipefail

PREFIX="${PIVITALS_PREFIX:-/opt/pi-vitals}"
SVC_USER="${PIVITALS_USER:-pivitals}"
PURGE=0

log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    -h | --help)
      echo "Usage: sudo ./deploy/uninstall.sh [--purge]   (--purge also deletes the history and the service user)"
      exit 0
      ;;
    *) die "unknown option: $arg" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "run as root: sudo ./deploy/uninstall.sh"

log "stopping the service"
systemctl disable --now pi-vitals >/dev/null 2>&1 || true
rm -f /etc/systemd/system/pi-vitals.service
rm -rf /etc/systemd/system/pi-vitals.service.d
systemctl daemon-reload

log "removing the Nginx site"
rm -f /etc/nginx/sites-enabled/pi-vitals /etc/nginx/sites-available/pi-vitals /etc/nginx/conf.d/pi-vitals.conf
rm -f /etc/nginx/pi-vitals.htpasswd
if command -v nginx >/dev/null && nginx -t >/dev/null 2>&1 && systemctl is-active --quiet nginx; then
  systemctl reload nginx
fi

log "removing the sudoers rule and the app"
rm -f /etc/sudoers.d/pi-vitals
rm -rf "$PREFIX"

if [ "$PURGE" -eq 1 ]; then
  log "purging history and the service user"
  rm -rf /var/lib/pi-vitals
  rm -f /etc/default/pi-vitals
  if id -u "$SVC_USER" >/dev/null 2>&1; then
    userdel "$SVC_USER" 2>/dev/null || true
  fi
else
  echo "Kept /var/lib/pi-vitals (history) and the '$SVC_USER' user. Use --purge to delete them."
fi

log "done"
