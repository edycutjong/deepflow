#!/bin/bash
# Nightly compressed pg_dump with 14-day rotation
set -e

BACKUP_DIR="/home/whale/silent_whale/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
FILENAME="silent_whale_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"
echo "[$(date)] Starting Postgres pg_dump via localhost..."

# Extract credentials safely from .env
export PGPASSWORD=$(grep -E '^POSTGRES_PASSWORD=' "$(dirname "$0")/../.env" | cut -d '=' -f2 | tr -d '"' | tr -d "'")
PGUSER=$(grep -E '^POSTGRES_USER=' "$(dirname "$0")/../.env" | cut -d '=' -f2 | tr -d '"' | tr -d "'")
PGDB=$(grep -E '^POSTGRES_DB=' "$(dirname "$0")/../.env" | cut -d '=' -f2 | tr -d '"' | tr -d "'")

# Bypass docker exec, connect directly to exposed localhost port
pg_dump -h 127.0.0.1 -p 5432 -U "$PGUSER" -d "$PGDB" | gzip > "$BACKUP_DIR/$FILENAME"

unset PGPASSWORD

echo "[$(date)] Backup securely gzipped: $FILENAME"
echo "[$(date)] Pruning backups older than 14 days..."
find "$BACKUP_DIR" -type f -name "*.sql.gz" -mtime +14 -exec rm {} \;
