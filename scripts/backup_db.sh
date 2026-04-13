#!/bin/bash
# Database backup script — daily pg_dump with 7-day rotation
# Usage: ./scripts/backup_db.sh
# Schedule via cron: 0 2 * * * /path/to/ai-trading-agent/scripts/backup_db.sh

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
DB_URL="${DATABASE_URL_SYNC:?DATABASE_URL_SYNC must be set}"
RETENTION_DAYS=7
DATE=$(date +%Y-%m-%d_%H%M%S)
FILENAME="goldbot_${DATE}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting backup..."

if pg_dump "$DB_URL" | gzip > "${BACKUP_DIR}/${FILENAME}"; then
    SIZE=$(du -h "${BACKUP_DIR}/${FILENAME}" | cut -f1)
    echo "[$(date)] Backup complete: ${FILENAME} (${SIZE})"
else
    echo "[$(date)] ERROR: Backup failed!" >&2
    exit 1
fi

# Rotate: delete backups older than RETENTION_DAYS
DELETED=$(find "$BACKUP_DIR" -name "goldbot_*.sql.gz" -mtime +${RETENTION_DAYS} -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[$(date)] Rotated: ${DELETED} old backups deleted"
fi

echo "[$(date)] Done. Active backups:"
ls -lh "$BACKUP_DIR"/goldbot_*.sql.gz 2>/dev/null || echo "  (none)"
