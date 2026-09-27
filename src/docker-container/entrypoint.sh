#!/bin/sh
set -eu

log() {
  printf '[ENTRYPOINT] %s\n' "$1"
}

STATUS_DIR="/run/unnamed-tracking"
STATUS_FILE="$STATUS_DIR/status.json"
DETAILS_FILE="$STATUS_DIR/details.txt"
BACKEND_LOG="$STATUS_DIR/backend.log"
MIGRATION_LOG="$STATUS_DIR/migration.log"
MIGRATION_RAW="$STATUS_DIR/migration.raw.log"
BACKEND_FIFO="$STATUS_DIR/backend.pipe"
NGINX_PID="/run/nginx.pid"

log "Initialising status directory"
mkdir -p "$STATUS_DIR"
: > "$DETAILS_FILE"
: > "$BACKEND_LOG"
: > "$MIGRATION_LOG"
: > "$MIGRATION_RAW"
rm -f "$BACKEND_FIFO"

write_status() {
  phase="$1"; overall="$2"; database="$3"; migrations="$4"; backend="$5"; frontend="$6"; message="$7"
  log "STATUS: $phase — $message"
  cat > "$STATUS_FILE" <<EOF
{"phase":"$phase","overall":"$overall","database":"$database","migrations":"$migrations","backend":"$backend","frontend":"$frontend","message":"$message"}
EOF
}

fail_startup() {
  phase="$1"; message="$2"; database="$3"; migrations="$4"; backend="$5"; frontend="$6"
  log "FAILURE: $phase — $message"
  printf '\nStartup failure: %s\n' "$message" >> "$DETAILS_FILE"
  write_status "$phase" "failed" "$database" "$migrations" "$backend" "$frontend" "$message"
  log "Detailed diagnostics remain available in container log output and /run/unnamed-tracking/"
  log "Entering failure hold-loop to keep Nginx alive"
  while :; do sleep 3600; done
}

cleanup() {
  log "Cleanup triggered"
  set +e
  if [ -n "${BACKEND_TAIL_PID:-}" ] && kill -0 "$BACKEND_TAIL_PID" 2>/dev/null; then
    log "Stopping backend log forwarding"
    kill "$BACKEND_TAIL_PID" 2>/dev/null
  fi
  if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    log "Stopping backend PID $BACKEND_PID"
    kill "$BACKEND_PID" 2>/dev/null
  fi
  if [ -f "$NGINX_PID" ]; then
    log "Stopping Nginx"
    nginx -s quit 2>/dev/null
  fi
}
trap cleanup INT TERM EXIT

log "Initializing Nginx with startup configuration"
write_status "INITIALIZING" "starting" "waiting" "waiting" "unknown" "unknown" "Starting production services."

cp /etc/nginx/startup.conf /etc/nginx/nginx.conf
nginx

log "Resolving application configuration"

if [ -n "${POSTGRES_USER:-}" ] || [ -n "${POSTGRES_PASSWORD:-}" ] || [ -n "${POSTGRES_DB:-}" ]; then
  if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_PASSWORD:-}" ] || [ -z "${POSTGRES_DB:-}" ]; then
    fail_startup "CONFIGURATION_FAILED" "POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB must be supplied together." "unknown" "unknown" "unknown" "unknown"
  fi
  DB_HEALTH_MODE="components"
  DB_HEALTH_HOST="${POSTGRES_HOST:-db}"
  DB_HEALTH_PORT="${POSTGRES_PORT:-5432}"
  DB_HEALTH_USER="$POSTGRES_USER"
  DB_HEALTH_DB="$POSTGRES_DB"
  export PGPASSWORD="$POSTGRES_PASSWORD"
elif [ -n "${DATABASE_URL:-}" ]; then
  printf '%s\n' "WARNING: DATABASE_URL is deprecated; use POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB." >> "$DETAILS_FILE"
  DB_HEALTH_MODE="url"
  DB_HEALTH_URL="$(printf "%s" "$DATABASE_URL" | sed "s#^postgresql+psycopg://#postgresql://#")"
else
  fail_startup "CONFIGURATION_FAILED" "Database configuration is missing. Set POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB." "unknown" "unknown" "unknown" "unknown"
fi

log "Waiting for PostgreSQL"
write_status "WAITING_FOR_DATABASE" "starting" "starting" "unknown" "unknown" "unknown" "Waiting for PostgreSQL."

attempt=1
while :; do
  if [ "${DB_HEALTH_MODE:-url}" = "components" ]; then
    if pg_isready -h "$DB_HEALTH_HOST" -p "$DB_HEALTH_PORT" -U "$DB_HEALTH_USER" -d "$DB_HEALTH_DB" >/dev/null 2>&1; then
      break
    fi
  elif pg_isready -d "$DB_HEALTH_URL" >/dev/null 2>&1; then
    break
  fi
  log "PostgreSQL not ready (attempt $attempt)"
  if [ "$attempt" -ge 60 ]; then fail_startup "DATABASE_FAILED" "PostgreSQL did not become ready within 120 seconds." "failed" "unknown" "unknown" "unknown"; fi
  attempt=$((attempt + 1)); sleep 2
done

log "PostgreSQL is ready"
write_status "DATABASE_READY" "starting" "ready" "unknown" "unknown" "unknown" "PostgreSQL is ready."

log "Running database migrations"
write_status "MIGRATING_DATABASE" "starting" "ready" "starting" "unknown" "unknown" "Applying database migrations."

attempt=1
while :; do
  : > "$MIGRATION_RAW"
  if alembic upgrade heads >"$MIGRATION_RAW" 2>&1; then
    python /srv/startup/redact_logs.py <"$MIGRATION_RAW" | tee -a "$MIGRATION_LOG"
    break
  fi
  python /srv/startup/redact_logs.py <"$MIGRATION_RAW" | tee -a "$MIGRATION_LOG" >/dev/null
  log "Migration attempt $attempt failed"
  if [ "$attempt" -ge 30 ]; then
    printf 'Migration attempts exhausted. See /run/unnamed-tracking/migration.log for command output.\n' >> "$DETAILS_FILE"
    fail_startup "MIGRATION_FAILED" "Database migrations failed after 30 attempts. Detailed migration output is retained at /run/unnamed-tracking/migration.log." "ready" "failed" "unknown" "unknown"
  fi
  attempt=$((attempt + 1)); sleep 2
done

log "Migrations completed"
printf '%s\n' "Database migrations completed successfully. Detailed migration output is retained at /run/unnamed-tracking/migration.log." >> "$DETAILS_FILE"
write_status "DATABASE_READY" "starting" "ready" "ready" "unknown" "unknown" "Database migrations completed."

log "Starting backend (FastAPI)"
write_status "STARTING_BACKEND" "starting" "ready" "ready" "starting" "unknown" "Starting FastAPI."

mkfifo "$BACKEND_FIFO"
python /srv/startup/redact_logs.py <"$BACKEND_FIFO" | tee "$BACKEND_LOG" &
BACKEND_TAIL_PID="$!"
uvicorn src.main:app --host 127.0.0.1 --port 8000 >"$BACKEND_FIFO" 2>&1 &
BACKEND_PID="$!"
log "Backend PID is $BACKEND_PID"

attempt=1
while ! curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; do
  log "Backend not healthy (attempt $attempt)"
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    log "Backend crashed during startup"
    printf '%s\n' "Backend process exited during startup. See /run/unnamed-tracking/backend.log for detailed backend output." >> "$DETAILS_FILE"
    fail_startup "BACKEND_FAILED" "The backend process exited during startup. Detailed backend output is retained at /run/unnamed-tracking/backend.log." "ready" "ready" "failed" "unknown"
  fi
  if [ "$attempt" -ge 60 ]; then
    log "Backend health timeout"
    printf '%s\n' "Backend health check timed out. See /run/unnamed-tracking/backend.log for detailed backend output." >> "$DETAILS_FILE"
    fail_startup "BACKEND_TIMEOUT" "The backend did not become healthy within 120 seconds. Detailed backend output is retained at /run/unnamed-tracking/backend.log." "ready" "ready" "failed" "unknown"
  fi
  attempt=$((attempt + 1)); sleep 2
done

log "Backend healthy"
write_status "STARTING_FRONTEND" "starting" "ready" "ready" "ready" "starting" "Activating the production frontend."

log "Testing ready.conf"
if ! nginx -t -c /etc/nginx/ready.conf; then
  fail_startup "FRONTEND_FAILED" "The production Nginx configuration failed validation. See Docker stderr for Nginx diagnostics." "ready" "ready" "ready" "failed"
fi

log "Overwriting active nginx.conf with ready.conf"
cp /etc/nginx/ready.conf /etc/nginx/nginx.conf

log "Reloading Nginx to activate production frontend"
if ! nginx -s reload; then
  fail_startup "FRONTEND_FAILED" "Nginx could not activate the production frontend configuration. See Docker stderr for Nginx diagnostics." "ready" "ready" "ready" "failed"
fi

attempt=1
while ! curl -fsS http://127.0.0.1/ >/dev/null 2>&1; do
  log "Frontend not ready (attempt $attempt)"
  if [ "$attempt" -ge 15 ]; then fail_startup "FRONTEND_FAILED" "Nginx could not serve the production frontend. See Docker stderr for Nginx diagnostics." "ready" "ready" "ready" "failed"; fi
  attempt=$((attempt + 1)); sleep 1
done

log "Frontend ready"
write_status "READY" "ready" "ready" "ready" "ready" "Unnamed Tracking is ready."
printf '%s\n' "Production application is ready. Detailed backend and migration diagnostics are retained inside the container and are also available through Docker logs." > "$DETAILS_FILE"

log "Entering backend crash monitor loop"
while :; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    log "Backend crashed after startup"
    printf '%s\n' "The backend stopped unexpectedly. See /run/unnamed-tracking/backend.log for detailed backend output." > "$DETAILS_FILE"
    write_status "BACKEND_CRASHED" "failed" "ready" "ready" "failed" "ready" "The backend stopped unexpectedly. Detailed backend output is retained at /run/unnamed-tracking/backend.log."
    while :; do sleep 3600; done
  fi
  sleep 2
done
