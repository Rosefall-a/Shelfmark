#!/bin/sh
set -e

echo "Starting application..."

echo "Applying database migrations..."
MAX_RETRIES=30
RETRY_DELAY=2
attempt=1
until alembic upgrade heads; do
  if [ "$attempt" -ge "$MAX_RETRIES" ]; then
    echo "Database migrations failed after $MAX_RETRIES attempts. Check the database and configuration above." >&2
    exit 1
  fi
  echo "Migration attempt $attempt failed; retrying in ${RETRY_DELAY}s..." >&2
  attempt=$((attempt + 1))
  sleep "$RETRY_DELAY"
done

echo "Starting API server..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
