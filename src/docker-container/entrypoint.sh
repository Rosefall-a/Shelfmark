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
BACKEND_PID=""

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
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    log "Stopping backend PID $BACKEND_PID"
    kill -TERM "$BACKEND_PID" 2>/dev/null
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -f "$NGINX_PID" ]; then
    log "Stopping Nginx"
    nginx -s quit 2>/dev/null || true
  fi
}

shutdown() {
  log "Shutdown signal received"
  exit 0
}

trap shutdown INT TERM
trap cleanup EXIT

log "Initialising status directory"
mkdir -p "$STATUS_DIR"
: > "$DETAILS_FILE"
: > "$BACKEND_LOG"
chmod 0644 "$STATUS_FILE" "$DETAILS_FILE" "$BACKEND_LOG" 2>/dev/null || true

log "Initialising Nginx with startup configuration"
write_status "INITIALIZING" "starting" "waiting" "waiting" "unknown" "unknown" "Starting production services."

cp /etc/nginx/startup.conf /etc/nginx/nginx.conf
if ! nginx -t; then
  fail_startup "FRONTEND_FAILED" "The startup Nginx configuration failed validation." "unknown" "unknown" "unknown" "failed"
fi
nginx

log "Resolving application configuration"
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

uvicorn src.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1 >"$BACKEND_LOG" 2>&1 &
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

log "Selecting production Nginx configuration"
case "${NGINX_TLS_ENABLED:-false}" in
  true|TRUE|1|yes|YES)
    case "${NGINX_TLS_REDIRECT_HTTP:-false}" in
      true|TRUE|1|yes|YES) selected_config="/etc/nginx/readytlsredirect.conf" ;;
      false|FALSE|0|no|NO|"") selected_config="/etc/nginx/readytls.conf" ;;
      *) fail_startup "FRONTEND_FAILED" "Invalid NGINX_TLS_REDIRECT_HTTP value." "ready" "ready" "ready" "failed" ;;
    esac
    ;;
  false|FALSE|0|no|NO|"")
    selected_config="/etc/nginx/ready.conf"
    ;;
  *)
    fail_startup "FRONTEND_FAILED" "Invalid NGINX_TLS_ENABLED value." "ready" "ready" "ready" "failed"
    ;;
esac

log "Rendering and activating $selected_config"
render_output="$({ /usr/local/bin/render-production-nginx "$selected_config" /etc/nginx/nginx.conf; } 2>&1)" || {
  printf '%s\n' "$render_output" >> "$DETAILS_FILE"
  fail_startup "FRONTEND_FAILED" "Production Nginx configuration is invalid. See startup details." "ready" "ready" "ready" "failed"
}

log "Testing active Nginx configuration"
nginx_output="$(nginx -t 2>&1)" || {
  printf '%s\n' "$nginx_output" >> "$DETAILS_FILE"
  fail_startup "FRONTEND_FAILED" "The production Nginx configuration failed validation." "ready" "ready" "ready" "failed"
}

log "Reloading Nginx to activate production frontend"
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
  