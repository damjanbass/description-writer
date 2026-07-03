#!/bin/sh
# Container entrypoint: wait for Postgres, run migrations, then exec the CMD
# (gunicorn by default, or `python web/manage.py qcluster` for the worker
# service — see deploy/docker-compose.yml).
set -e

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-korpus}"
POSTGRES_USER="${POSTGRES_USER:-korpus}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"

echo "entrypoint: waiting for Postgres at ${POSTGRES_HOST}:${POSTGRES_PORT}..."

attempt=0
max_attempts=30
until python -c "
import os
import sys

import psycopg

try:
    conn = psycopg.connect(
        host=os.environ.get('POSTGRES_HOST', 'localhost'),
        port=os.environ.get('POSTGRES_PORT', '5432'),
        dbname=os.environ.get('POSTGRES_DB', 'korpus'),
        user=os.environ.get('POSTGRES_USER', 'korpus'),
        password=os.environ.get('POSTGRES_PASSWORD', ''),
        connect_timeout=1,
    )
    conn.close()
except Exception as exc:
    sys.stderr.write('entrypoint: postgres not ready yet (%s)\n' % exc)
    sys.exit(1)
"; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$max_attempts" ]; then
        echo "entrypoint: Postgres did not become available after ${max_attempts}s, giving up." >&2
        exit 1
    fi
    sleep 1
done

echo "entrypoint: Postgres is available."

python web/manage.py migrate --noinput
python web/manage.py createcachetable

exec "$@"
