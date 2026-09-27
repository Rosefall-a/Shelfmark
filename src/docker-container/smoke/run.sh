#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"
PROJECT_NAME="${SMOKE_PROJECT_NAME:-unnamed-tracking-runtime-smoke}"
SMOKE_IMAGE="${SMOKE_IMAGE:-unnamed_tracking_app:runtime-smoke}"
ARTIFACT_DIR="${SMOKE_ARTIFACT_DIR:-${RUNNER_TEMP:-$SCRIPT_DIR}/production-runtime-smoke}"
BASE_URL="http://127.0.0.1:18080"
COMPOSE=(docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE")
APP_CONTAINER="$PROJECT_NAME-app-1"
DB_CONTAINER="$PROJECT_NAME-db-1"
INVALID_CONTAINER="${PROJECT_NAME}-invalid-config"
DB_FAILURE_CONTAINER="${PROJECT_NAME}-db-unavailable"
MIGRATION_FAILURE_CONTAINER="${PROJECT_NAME}-migration-failure"
BACKEND_FAILURE_CONTAINER="${PROJECT_NAME}-backend-failure"

mkdir -p "$ARTIFACT_DIR"
printf 'Production runtime smoke image: %s\n' "$SMOKE_IMAGE" | tee "$ARTIFACT_DIR/run.txt"

collect_diagnostics() {
  set +e
  {
    echo "=== compose ps ==="
    "${COMPOSE[@]}" ps -a
    echo
    echo "=== compose logs ==="
    "${COMPOSE[@]}" logs --no-color --timestamps
    echo
    echo "=== app status ==="
    docker exec "$APP_CONTAINER" cat /run/unnamed-tracking/status.json
    echo
    echo "=== app details ==="
    docker exec "$APP_CONTAINER" cat /run/unnamed-tracking/details.txt
    echo
    echo "=== backend log ==="
    docker exec "$APP_CONTAINER" cat /run/unnamed-tracking/backend.log
    echo
    echo "=== nginx configuration ==="
    docker exec "$APP_CONTAINER" nginx -T
  } >"$ARTIFACT_DIR/diagnostics.txt" 2>&1

  for pair in \
    "$INVALID_CONTAINER:invalid-config" \
    "$DB_FAILURE_CONTAINER:db-unavailable" \
    "$MIGRATION_FAILURE_CONTAINER:migration-failure" \
    "$BACKEND_FAILURE_CONTAINER:backend-failure"; do
    container="${pair%%:*}"
    name="${pair#*:}"
    if docker inspect "$container" >/dev/null 2>&1; then
      {
        echo "=== $name logs ==="
        docker logs --timestamps "$container"
        echo
        echo "=== $name status ==="
        docker exec "$container" cat /run/unnamed-tracking/status.json
        echo
        echo "=== $name details ==="
        docker exec "$container" cat /run/unnamed-tracking/details.txt
        echo
        echo "=== $name backend log ==="
        docker exec "$container" cat /run/unnamed-tracking/backend.log
      } >"$ARTIFACT_DIR/$name.txt" 2>&1
    fi
  done
}

cleanup() {
  rc=$?
  set +e
  collect_diagnostics
  "${COMPOSE[@]}" down -v --remove-orphans
  docker rm -f "$INVALID_CONTAINER" "$DB_FAILURE_CONTAINER" "$MIGRATION_FAILURE_CONTAINER" "$BACKEND_FAILURE_CONTAINER" >/dev/null 2>&1 || true
  exit "$rc"
}
trap cleanup EXIT INT TERM

wait_for_db() {
  for _ in {1..60}; do
    if "${COMPOSE[@]}" exec -T db pg_isready -U smoke -d smoke >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "PostgreSQL did not become ready." >&2
  return 1
}

read_status() {
  local container="$1"
  docker exec "$container" cat /run/unnamed-tracking/status.json
}

wait_for_phase() {
  local container="$1"
  local expected="$2"
  local attempts="${3:-120}"
  local status phase
  for _ in $(seq 1 "$attempts"); do
    status="$(read_status "$container" 2>/dev/null || true)"
    phase="$(printf '%s' "$status" | sed -n 's/.*"phase":"\\([^"]*\\)".*/\\1/p')"
    if [[ "$phase" == "$expected" ]]; then
      printf '%s\n' "$status"
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for $container to reach $expected." >&2
  return 1
}

assert_status_field() {
  local status="$1"
  local field="$2"
  local expected="$3"
  local value
  value="$(printf '%s' "$status" | sed -n "s/.*\"$field\":\"\\([^\"]*\\)\\".*/\\1/p")"
  if [[ "$value" != "$expected" ]]; then
    echo "Expected $field=$expected, got $value from: $status" >&2
    return 1
  fi
}

assert_failure_phase() {
  local container="$1"
  local expected="$2"
  local status
  status="$(wait_for_phase "$container" "$expected" 130)"
  assert_status_field "$status" overall failed
  echo "$status"
}

echo "Starting disposable PostgreSQL container."
"${COMPOSE[@]}" up -d db
wait_for_db

echo "Stopping PostgreSQL to exercise startup diagnostics before readiness."
"${COMPOSE[@]}" stop db

echo "Starting production image with the database temporarily unavailable."
"${COMPOSE[@]}" up -d app
startup_status="$(wait_for_phase "$APP_CONTAINER" WAITING_FOR_DATABASE 15)"
assert_status_field "$startup_status" database starting

echo "Startup diagnostics are reachable before PostgreSQL is ready."
curl --fail --silent --show-error "$BASE_URL/_startup/status.json?ts=$RANDOM" >"$ARTIFACT_DIR/pre-ready-status.json"
curl --fail --silent --show-error "$BASE_URL/_startup/details.txt?ts=$RANDOM" >"$ARTIFACT_DIR/pre-ready-details.txt"

echo "Starting PostgreSQL and waiting for the production entrypoint."
"${COMPOSE[@]}" start db
wait_for_db
ready_status="$(wait_for_phase "$APP_CONTAINER" READY 150)"
assert_status_field "$ready_status" overall ready
for component in database migrations backend frontend; do
  assert_status_field "$ready_status" "$component" ready
done

echo "Checking readiness through the Nginx diagnostic endpoint."
curl --fail --silent --show-error "$BASE_URL/_startup/status.json?ts=$RANDOM" >"$ARTIFACT_DIR/ready-status.json"

echo "Checking that Nginx is serving the compiled frontend."
frontend_response="$(curl --fail --silent --show-error "$BASE_URL/")"
printf '%s\n' "$frontend_response" >"$ARTIFACT_DIR/frontend.html"
grep -q '<div id="app">' "$ARTIFACT_DIR/frontend.html"
if grep -q 'Starting application' "$ARTIFACT_DIR/frontend.html"; then
  echo "Production Nginx is still serving the startup page." >&2
  exit 1
fi

echo "Checking Nginx production configuration."
docker exec "$APP_CONTAINER" nginx -T >"$ARTIFACT_DIR/nginx-config.txt" 2>&1
grep -q 'listen 80;' "$ARTIFACT_DIR/nginx-config.txt"
grep -q 'root /srv/frontend;' "$ARTIFACT_DIR/nginx-config.txt"
grep -q 'proxy_pass http://127.0.0.1:8000;' "$ARTIFACT_DIR/nginx-config.txt"

echo "Checking backend health on the internal loopback."
docker exec "$APP_CONTAINER" curl --fail --silent --show-error http://127.0.0.1:8000/health >"$ARTIFACT_DIR/backend-health.json"

echo "Checking Alembic heads match the current database revision."
heads="$(docker exec "$APP_CONTAINER" sh -c 'alembic heads 2>/dev/null | grep -Eo "[0-9a-f]{12}" | sort -u')"
current="$(docker exec "$APP_CONTAINER" sh -c 'alembic current 2>/dev/null | grep -Eo "[0-9a-f]{12}" | sort -u')"
printf 'heads:\n%s\ncurrent:\n%s\n' "$heads" "$current" | tee "$ARTIFACT_DIR/alembic.txt"
[[ -n "$heads" && "$heads" == "$current" ]]

echo "Checking a representative database-backed API request through Nginx."
login_response="$(curl --fail --silent --show-error -c "$ARTIFACT_DIR/cookies.txt" \
  -H 'Content-Type: application/json' \
  -d '{"username_or_email":"smoke","password":"smoke-password"}' \
  "$BASE_URL/api/auth/login")"
printf '%s\n' "$login_response" >"$ARTIFACT_DIR/login.json"
me_response="$(curl --fail --silent --show-error -b "$ARTIFACT_DIR/cookies.txt" "$BASE_URL/api/auth/me")"
printf '%s\n' "$me_response" >"$ARTIFACT_DIR/api-me.json"
printf '%s\n' "$me_response" | grep -q '"username":"smoke"'

echo "Checking shutdown cleanup behavior of the current production artifact."
"${COMPOSE[@]}" stop -t 10 app || true
docker logs "$APP_CONTAINER" >"$ARTIFACT_DIR/shutdown.log" 2>&1 || true
grep -q 'Cleanup triggered' "$ARTIFACT_DIR/shutdown.log"

echo "Controlled failure: invalid database configuration."
docker run -d --name "$INVALID_CONTAINER" -p 18081:80 "$SMOKE_IMAGE" >/dev/null
assert_failure_phase "$INVALID_CONTAINER" CONFIGURATION_FAILED
curl --fail --silent --show-error "http://127.0.0.1:18081/_startup/status.json?ts=$RANDOM" >"$ARTIFACT_DIR/invalid-config-status.json"
docker rm -f "$INVALID_CONTAINER" >/dev/null

echo "Controlled failure: database unavailable."
docker run -d --name "$DB_FAILURE_CONTAINER" -p 18082:80 \
  -e POSTGRES_HOST=smoke-db-that-does-not-exist \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=smoke \
  -e POSTGRES_PASSWORD=smoke-password \
  -e POSTGRES_DB=smoke \
  -e SECRET_KEY=smoke-test-secret-key \
  -e PRIMARY_USER_USERNAME=smoke \
  -e PRIMARY_USER_EMAIL=smoke@example.invalid \
  -e PRIMARY_USER_PASSWORD=smoke-password \
  "$SMOKE_IMAGE" >/dev/null
wait_for_phase "$DB_FAILURE_CONTAINER" WAITING_FOR_DATABASE 15 >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:18082/_startup/status.json?ts=$RANDOM" >"$ARTIFACT_DIR/db-unavailable-status.json"
docker rm -f "$DB_FAILURE_CONTAINER" >/dev/null

echo "Controlled failure: migration failure."
"${COMPOSE[@]}" start db
wait_for_db
"${COMPOSE[@]}" exec -T db psql -U smoke -d smoke -v ON_ERROR_STOP=1 -c \
  "CREATE DATABASE smoke_migration_failure;"
"${COMPOSE[@]}" exec -T db psql -U smoke -d smoke -v ON_ERROR_STOP=1 -c \
  "CREATE ROLE smoke_restricted LOGIN PASSWORD 'restricted-password';"
"${COMPOSE[@]}" exec -T db psql -U smoke -d smoke -v ON_ERROR_STOP=1 -c \
  "GRANT CONNECT ON DATABASE smoke_migration_failure TO smoke_restricted;"
"${COMPOSE[@]}" exec -T db psql -U smoke -d smoke_migration_failure -v ON_ERROR_STOP=1 -c \
  "REVOKE ALL ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO smoke_restricted; REVOKE CREATE ON SCHEMA public FROM smoke_restricted;"
docker run -d --name "$MIGRATION_FAILURE_CONTAINER" --network "${PROJECT_NAME}_default" \
  -e POSTGRES_HOST=db -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=smoke_restricted -e POSTGRES_PASSWORD=restricted-password \
  -e POSTGRES_DB=smoke_migration_failure \
  -e SECRET_KEY=smoke-test-secret-key \
  -e PRIMARY_USER_USERNAME=smoke -e PRIMARY_USER_EMAIL=smoke@example.invalid \
  -e PRIMARY_USER_PASSWORD=smoke-password \
  "$SMOKE_IMAGE" >/dev/null
assert_failure_phase "$MIGRATION_FAILURE_CONTAINER" MIGRATION_FAILED
docker rm -f "$MIGRATION_FAILURE_CONTAINER" >/dev/null

echo "Controlled failure: backend startup failure."
fake_main="$ARTIFACT_DIR/failing-main.py"
cat >"$fake_main" <<'PY'
raise RuntimeError("intentional production smoke-test backend startup failure")
PY
docker run -d --name "$BACKEND_FAILURE_CONTAINER" --network "${PROJECT_NAME}_default" -p 18083:80 \
  -e POSTGRES_HOST=db -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=smoke -e POSTGRES_PASSWORD=smoke-password -e POSTGRES_DB=smoke \
  -e SECRET_KEY=smoke-test-secret-key \
  -e PRIMARY_USER_USERNAME=smoke -e PRIMARY_USER_EMAIL=smoke@example.invalid \
  -e PRIMARY_USER_PASSWORD=smoke-password \
  -v "$fake_main:/app/src/main.py:ro" \
  "$SMOKE_IMAGE" >/dev/null
assert_failure_phase "$BACKEND_FAILURE_CONTAINER" BACKEND_FAILED
curl --fail --silent --show-error "http://127.0.0.1:18083/_startup/status.json?ts=$RANDOM" >"$ARTIFACT_DIR/backend-failure-status.json"
docker rm -f "$BACKEND_FAILURE_CONTAINER" >/dev/null

echo "Production runtime smoke tests passed."
