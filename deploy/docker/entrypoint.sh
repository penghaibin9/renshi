#!/bin/bash
set -euo pipefail

echo "Starting Yueke Higher-Education HR..."

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-3306}"

echo "Waiting for MySQL at ${DB_HOST}:${DB_PORT}..."
MAX_TRIES=60
COUNT=0
while ! nc -z "$DB_HOST" "$DB_PORT"; do
  COUNT=$((COUNT + 1))
  if [ "$COUNT" -ge "$MAX_TRIES" ]; then
    echo "ERROR: MySQL not available at ${DB_HOST}:${DB_PORT} after $MAX_TRIES attempts"
    exit 1
  fi
  sleep 1
done
echo "MySQL TCP endpoint is ready."

# A database name/user rename in Compose does not mutate an existing MySQL
# data volume.  Probe the canonical URL first and, for local upgrades only,
# fall back to the explicitly configured legacy URL.  This keeps fresh
# installs on the canonical schema without forcing operators to discard or
# manually rewrite an existing development database.
if [ -n "${LEGACY_DATABASE_URL:-}" ]; then
  if ! python - <<'PY'
import os
from urllib.parse import parse_qs, unquote, urlparse

import MySQLdb


def connect(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    connection = MySQLdb.connect(
        host=parsed.hostname or "db",
        port=parsed.port or 3306,
        user=unquote(parsed.username or ""),
        passwd=unquote(parsed.password or ""),
        db=parsed.path.lstrip("/"),
        charset=query.get("charset", ["utf8mb4"])[0],
        connect_timeout=5,
    )
    connection.close()


try:
    connect(os.environ["DATABASE_URL"])
except MySQLdb.Error:
    raise SystemExit(1)
PY
  then
    if LEGACY_DATABASE_URL="$LEGACY_DATABASE_URL" python - <<'PY'
import os
from urllib.parse import parse_qs, unquote, urlparse

import MySQLdb

parsed = urlparse(os.environ["LEGACY_DATABASE_URL"])
query = parse_qs(parsed.query)
try:
    connection = MySQLdb.connect(
        host=parsed.hostname or "db",
        port=parsed.port or 3306,
        user=unquote(parsed.username or ""),
        passwd=unquote(parsed.password or ""),
        db=parsed.path.lstrip("/"),
        charset=query.get("charset", ["utf8mb4"])[0],
        connect_timeout=5,
    )
    connection.close()
except MySQLdb.Error:
    raise SystemExit(1)
PY
    then
      echo "Canonical local database is unavailable; using the compatible existing schema."
      export DATABASE_URL="$LEGACY_DATABASE_URL"
    else
      echo "ERROR: neither the canonical nor compatible existing database is accessible."
      exit 1
    fi
  fi
fi

# Development may use the documented weak key. Production is fail-closed in
# Django settings and must provide a unique secret explicitly.
SECRET_KEY_FILE="/app/.runtime/media/.generated_secret_key"
case "${SECRET_KEY:-}" in
  ""|"django-insecure-default-key"|"dev-secret-key-change-in-production"|change-me*|django-insecure-*)
    if [ "${HORILLA_ENV:-}" = "production" ] || [ "${DEBUG:-1}" = "0" ] || [ "${DEBUG:-}" = "False" ]; then
      echo "ERROR: production requires an explicit strong SECRET_KEY"
      exit 1
    fi
    if [ -f "$SECRET_KEY_FILE" ]; then
      SECRET_KEY="$(cat "$SECRET_KEY_FILE")"
    else
      SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"
      mkdir -p "$(dirname "$SECRET_KEY_FILE")"
      printf '%s' "$SECRET_KEY" > "$SECRET_KEY_FILE"
      chmod 600 "$SECRET_KEY_FILE"
    fi
    export SECRET_KEY
    ;;
esac

is_production=false
if [ "${HORILLA_ENV:-}" = "production" ] || [ "${DEBUG:-1}" = "0" ] || [ "${DEBUG:-}" = "False" ]; then
  is_production=true
fi

# In production, schema migration and collectstatic belong to one release job,
# not every web replica. Development keeps the convenient automatic behavior.
if [ -z "${MIGRATE_ON_START:-}" ]; then
  if $is_production; then MIGRATE_ON_START=0; else MIGRATE_ON_START=1; fi
fi
if [ -z "${COLLECTSTATIC_ON_START:-}" ]; then
  if $is_production; then COLLECTSTATIC_ON_START=0; else COLLECTSTATIC_ON_START=1; fi
fi
if [ -z "${CHECK_ON_START:-}" ]; then
  if $is_production; then CHECK_ON_START=0; else CHECK_ON_START=1; fi
fi

prepare_args=()
if [ "$MIGRATE_ON_START" = "1" ] || [ "$MIGRATE_ON_START" = "true" ] || [ "$MIGRATE_ON_START" = "True" ]; then
  prepare_args+=("--migrate")
fi
if [ "$COLLECTSTATIC_ON_START" = "1" ] || [ "$COLLECTSTATIC_ON_START" = "true" ] || [ "$COLLECTSTATIC_ON_START" = "True" ]; then
  prepare_args+=("--collectstatic")
fi
if [ "$CHECK_ON_START" = "1" ] || [ "$CHECK_ON_START" = "true" ] || [ "$CHECK_ON_START" = "True" ]; then
  python manage.py prepare_runtime "${prepare_args[@]}"
elif [ "${#prepare_args[@]}" -gt 0 ]; then
  python manage.py prepare_runtime "${prepare_args[@]}"
fi

echo "Starting server..."
exec "$@"
