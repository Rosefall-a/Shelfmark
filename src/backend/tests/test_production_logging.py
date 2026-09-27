"""Regression tests for the production container logging/startup presentation contract."""

from pathlib import Path
import re

ROOT = Path(__file__).parents[2].parents[0]
DOCKER = ROOT / "docker-container"


def read(path: str) -> str:
    return (DOCKER / path).read_text(encoding="utf-8")


def test_startup_page_does_not_render_raw_logs_by_default() -> None:
    html = read("startup/startup.html")
    javascript = read("startup/startup.js")

    assert "/_startup/backend.log" not in html
    assert "/_startup/migration.log" not in html
    assert "details.open = failed" in javascript
    assert "backend.log" not in javascript
    assert "migration.log" not in javascript


def test_startup_page_preserves_concise_failure_presentation() -> None:
    html = read("startup/startup.html")
    javascript = read("startup/startup.js")

    assert 'id="failure-icon"' in html
    assert 'titleEl.textContent = "Application failed"' in javascript
    assert 's.overall === "failed"' in javascript


def test_detailed_logs_are_not_public_http_resources() -> None:
    startup_nginx = read("nginx/startup.conf")
    ready_nginx = read("nginx/ready.conf")

    for nginx in (startup_nginx, ready_nginx):
        assert "/_startup/backend.log" not in nginx
        assert "/_startup/migration.log" not in nginx


def test_entrypoint_keeps_detailed_logs_outside_startup_details() -> None:
    entrypoint = (DOCKER / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'BACKEND_LOG="$STATUS_DIR/backend.log"' in entrypoint
    assert 'MIGRATION_LOG="$STATUS_DIR/migration.log"' in entrypoint
    assert 'cat "$BACKEND_LOG" >> "$DETAILS_FILE"' not in entrypoint
    assert 'cat "$BACKEND_LOG" > "$DETAILS_FILE"' not in entrypoint

    log_messages = re.findall(r'(?m)^\s*log "([^"]*)"', entrypoint)
    forbidden = ("password", "token", "api key", "secret", "private key", "webhook")
    assert log_messages
    assert all(not any(term in message.lower() for term in forbidden) for message in log_messages)


def test_nginx_errors_are_sent_to_container_stderr() -> None:
    for path in ("nginx/startup.conf", "nginx/ready.conf"):
        assert "error_log /dev/stderr warn;" in read(path)


def test_startup_status_contract_covers_success_and_failures() -> None:
    entrypoint = (DOCKER / "entrypoint.sh").read_text(encoding="utf-8")

    for phase in (
        "CONFIGURATION_FAILED",
        "DATABASE_FAILED",
        "MIGRATION_FAILED",
        "BACKEND_FAILED",
        "BACKEND_TIMEOUT",
        "FRONTEND_FAILED",
        "BACKEND_CRASHED",
        "READY",
    ):
        assert phase in entrypoint

    assert 'write_status "DATABASE_READY" "starting" "ready" "ready"' in entrypoint
    assert 'write_status "READY" "ready" "ready" "ready" "ready" "Unnamed Tracking is ready."' in entrypoint


def test_failure_diagnostics_identify_operator_log_locations() -> None:
    entrypoint = (DOCKER / "entrypoint.sh").read_text(encoding="utf-8")

    assert "/run/unnamed-tracking/migration.log" in entrypoint
    assert "/run/unnamed-tracking/backend.log" in entrypoint
    assert "See Docker stderr for Nginx diagnostics." in entrypoint
    assert "Entering failure hold-loop to keep Nginx alive" in entrypoint
