#!/usr/bin/env bash
#
# Korpus nightly backup: Postgres dump + media volume tarball, with a
# 14-day local retention window.
#
# Install as a root cron job (crontab -e as root, or a file dropped in
# /etc/cron.d/korpus-backup):
#
#   0 3 * * * /opt/korpus/deploy/backup.sh >> /var/log/korpus-backup.log 2>&1
#
# Run this script from anywhere; it cds into the compose project directory
# itself. Requires the `docker compose` plugin and the stack already
# running (docker compose -f deploy/docker-compose.yml up -d).

set -euo pipefail

# -----------------------------------------------------------------------
# Config — override via environment if your setup differs from the docs.
# -----------------------------------------------------------------------
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-korpus}"
COMPOSE_FILE="${COMPOSE_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker-compose.yml}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/korpus}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

# Named volume Docker Compose creates for the media mount: by default
# Compose prefixes every volume with the project name, i.e.
# "<project>_media" for a volume declared as `media:` in docker-compose.yml.
# If COMPOSE_PROJECT_NAME is customized (via .env or -p), this tracks it
# automatically; override MEDIA_VOLUME directly if the volume was renamed.
MEDIA_VOLUME="${MEDIA_VOLUME:-${COMPOSE_PROJECT_NAME}_media}"

# Load DB creds from .env if present and not already exported.
ENV_FILE="${ENV_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env}"
if [ -f "$ENV_FILE" ]; then
	# shellcheck disable=SC1090
	set -a
	source "$ENV_FILE"
	set +a
fi

POSTGRES_USER="${POSTGRES_USER:-korpus}"
POSTGRES_DB="${POSTGRES_DB:-korpus}"

log() {
	printf '%s korpus-backup: %s\n' "$(date -u +%FT%TZ)" "$1"
}

mkdir -p "$BACKUP_DIR"

STAMP="$(date +%F)"
DB_DUMP="$BACKUP_DIR/db-$STAMP.sql.gz"
MEDIA_TAR="$BACKUP_DIR/media-$STAMP.tar.gz"

# -----------------------------------------------------------------------
# 1. Postgres dump
# -----------------------------------------------------------------------
log "starting Postgres dump -> $DB_DUMP"
docker compose -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" exec -T db \
	pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$DB_DUMP"
log "Postgres dump complete ($(du -h "$DB_DUMP" | cut -f1))"

# -----------------------------------------------------------------------
# 2. Media volume tarball (via a throwaway container mounting the volume)
# -----------------------------------------------------------------------
log "starting media volume tar -> $MEDIA_TAR (volume: $MEDIA_VOLUME)"
docker run --rm \
	-v "${MEDIA_VOLUME}:/data:ro" \
	-v "${BACKUP_DIR}:/backup" \
	alpine:3 \
	tar czf "/backup/media-$STAMP.tar.gz" -C /data .
log "media tar complete ($(du -h "$MEDIA_TAR" | cut -f1))"

# -----------------------------------------------------------------------
# 3. Rotate: delete backups older than RETENTION_DAYS
# -----------------------------------------------------------------------
log "rotating backups older than $RETENTION_DAYS days in $BACKUP_DIR"
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db-*.sql.gz' -o -name 'media-*.tar.gz' \) \
	-mtime "+$RETENTION_DAYS" -print -delete | while read -r stale; do
	log "removed stale backup: $stale"
done

log "backup run complete"
