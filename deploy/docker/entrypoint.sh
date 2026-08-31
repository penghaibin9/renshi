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

if [ "$MIGRATE_ON_START" = "1" ] || [ "$MIGRATE_ON_START" = "true" ] || [ "$MIGRATE_ON_START" = "True" ]; then
  python manage.py migrate --noinput
fi

if [ "$COLLECTSTATIC_ON_START" = "1" ] || [ "$COLLECTSTATIC_ON_START" = "true" ] || [ "$COLLECTSTATIC_ON_START" = "True" ]; then
  python manage.py collectstatic --noinput
fi

python manage.py check

echo "Starting server..."
exec "$@"
