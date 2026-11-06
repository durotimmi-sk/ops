#!/usr/bin/env bash
set -euo pipefail

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DB=/var/lib/opspilot/opspilot.sqlite3
BACKUP_DIR=/var/backups/opspilot
TEMP_FILE=${BACKUP_DIR}/.opspilot-${STAMP}.sqlite3.tmp
BACKUP_FILE=${BACKUP_DIR}/opspilot-${STAMP}.sqlite3

if [[ ! -s "$DB" ]]; then
  echo "OpsPilot database is missing or empty." >&2
  exit 1
fi

python3 - "$DB" "$TEMP_FILE" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as source, sqlite3.connect(sys.argv[2]) as backup:
    source.backup(backup)
    result = backup.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit("SQLite backup integrity check failed: " + str(result))
PY

chmod 0600 "$TEMP_FILE"
mv "$TEMP_FILE" "$BACKUP_FILE"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'opspilot-*.sqlite3' -mtime +30 -delete
