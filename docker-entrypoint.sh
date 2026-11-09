#!/bin/sh
# Docker skapar bind-mounten ./data som root. Rätta ägaren och kör sedan appen som vanlig användare.
set -e
DATA_DIR="${DATA_DIR:-/data}"
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  chown -R 1000:1000 "$DATA_DIR" 2>/dev/null || true
  if command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid=1000 --regid=1000 --clear-groups "$@"
  fi
fi
exec "$@"
