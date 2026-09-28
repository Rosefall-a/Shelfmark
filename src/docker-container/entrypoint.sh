#!/bin/sh
set -eu

log() {
  printf '[ENTRYPOINT] %s\n' "$1"
}

STATUS_DIR="/run/unnamed-tracking"
STATUS_FILE="$STATUS_DIR/status.json"
DETAILS_FILE="$STATUS_DIR/details.txt"
BACKEND_LOG="$STATUS_DIR/backend.log"
NGINX_PID="/run/nginx.pid"

log "Initialising status directory"
mkdir -p "$STATUS_DIR"
: > "$DETAILS_FILE"
: > "$BACKEND_LOG"

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
  log "Entering failure hold-loop to keep Nginx alive"
  while :; do sleep 3600; done
}

cleanup() {
  log "Cleanup triggered"
  set +e
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

# 1. Overwrite the default config file with your startup rules
cp /etc/nginx/startup.conf /etc/nginx/nginx.conf

# 2. Start Nginx using the standard default path (no -c flag)
nginx


log "Resolving application configuration"
#write_status "CONFIGURING" "starting" "unknown" "unknown" "unknown" "unknown" "Resolving environment and persistent configuration."
#CONFIG_REPORT="$(python - <<'PY'
#from src.core.env_handler import EnvConfigHandler

#handler = EnvConfigHandler()
#summary = handler.startup_summary()
#for issue in summary["issues"]:
#    print(f"{issue['severity'].upper()}: {issue['message']}")
#if not summary["ready"]:
#    raise SystemExit(1)
#PY
#)" || fail_startup "CONFIGURATION_FAILED" "Application configuration contains an unrecoverable error. See startup details for the exact fields." "unknown" "unknown" "unknown" "unknown"
#if [ -n "$CONFIG_REPORT" ]; then
#  printf "%s\n" "$CONFIG_REPORT" >> "$DETAILS_FILE"
#fi

if [ -n "${POSTGRES_USER:-}" ] || [ -n "${POSTGRES_PASSWORD:-}" ] || [ -n "${POSTGRES_DB:-}" ]; then
  if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_PASSWORD:-}" ] || [ -z "${POSTGRES_DB:-}" ]; then
    fail_startup "CONFIGURATION_FAILED" "POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB must be supplied together." "unknown" "unknown" "unknown" "unknown"
  fi
  DB_HEALTH_MODE="components"
  DB_HEALTH_HOST="${POSTGRES_HOST:-db}"
  DB_HEALTH_PORT="${POSTGRES_PORT:-5432}"
  DB_HEALTH_USER="${POSTGRES_USER}"
  DB_HEALTH_DB="${POSTGRES_DB}"
  export PGPASSWORD="${POSTGRES_PASSWORD}"
elif [ -n "${DATABASE_URL:-}" ]; then
  printf "%s\n" "WARNING: DATABASE_URL is deprecated; use POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB." >> "$DETAILS_FILE"
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
until alembic upgrade heads >>"$DETAILS_FILE" 2>&1; do
  log "Migration attempt $attempt failed"
  if [ "$attempt" -ge 30 ]; then fail_startup "MIGRATION_FAILED" "Database migrations failed after 30 attempts." "ready" "failed" "unknown" "unknown"; fi
  attempt=$((attempt + 1)); sleep 2
done

log "Migrations completed"
write_status "DATABASE_READY" "starting" "ready" "ready" "unknown" "unknown" "Database migrations completed."

log "Starting backend (FastAPI)"
write_status "STARTING_BACKEND" "starting" "ready" "ready" "starting" "unknown" "Starting FastAPI."

uvicorn src.main:app --host 127.0.0.1 --port 8000 >"$BACKEND_LOG" 2>&1 &
BACKEND_PID="$!"
log "Backend PID is $BACKEND_PID"

attempt=1
while ! curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; do
  log "Backend not healthy (attempt $attempt)"
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    log "Backend crashed during startup"
    cat "$BACKEND_LOG" >> "$DETAILS_FILE" 2>/dev/null || true
    fail_startup "BACKEND_FAILED" "The backend process exited during startup." "ready" "ready" "failed" "unknown"
  fi
  if [ "$attempt" -ge 60 ]; then
    log "Backend health timeout"
    cat "$BACKEND_LOG" >> "$DETAILS_FILE" 2>/dev/null || true
    fail_startup "BACKEND_TIMEOUT" "The backend did not become healthy within 120 seconds." "ready" "ready" "failed" "unknown"
  fi
  attempt=$((attempt + 1)); sleep 2
done

log "Backend healthy"
write_status "STARTING_FRONTEND" "starting" "ready" "ready" "ready" "starting" "Activating the production frontend."

log "Testing ready.conf"
if ! nginx -t -c /etc/nginx/ready.conf; then
  fail_startup "FRONTEND_FAILED" "The production Nginx configuration failed validation." "ready" "ready" "ready" "failed"
fi

log "Overwriting active nginx.conf with ready.conf"
# 2. Physically replace the main configuration file
cp /etc/nginx/ready.conf /etc/nginx/nginx.conf

log "Reloading Nginx to activate production frontend"
# 3. Trigger a standard reload. Nginx reads the newly copied rules seamlessly.
if ! nginx -s reload; then
  fail_startup "FRONTEND_FAILED" "Nginx could not activate the production frontend configuration." "ready" "ready" "ready" "failed"
fi

attempt=1
while ! curl -fsS http://127.0.0.1/ >/dev/null 2>&1; do
  log "Frontend not ready (attempt $attempt)"
  if [ "$attempt" -ge 15 ]; then fail_startup "FRONTEND_FAILED" "Nginx could not serve the production frontend." "ready" "ready" "ready" "failed"; fi
  attempt=$((attempt + 1)); sleep 1
done

log "Frontend ready"
write_status "READY" "ready" "ready" "ready" "ready" "ready" "Unnamed Tracking is ready."
printf '%s\n' "Production application is ready." > "$DETAILS_FILE"

log "Entering backend crash monitor loop"
while :; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    log "Backend crashed after startup"
    cat "$BACKEND_LOG" > "$DETAILS_FILE" 2>/dev/null || true
    write_status "BACKEND_CRASHED" "failed" "ready" "ready" "failed" "ready" "The backend stopped unexpectedly."
    while :; do sleep 3600; done
  fi
  sleep 2
done
