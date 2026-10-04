#!/bin/sh
set -e
  
echo "Starting application..."

# Brings the database up to date: waits for it, adopts a database made by an
# older (squashed) migration history instead of failing on its unknown
# revision, then runs every newer migration. A real failure stops the
# container with the reason instead of retrying the same error.
# See src/database/migrate.py and docs/migrations.md.
echo "Preparing database..."
python -m src.database.migrate

echo "Starting API server..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
