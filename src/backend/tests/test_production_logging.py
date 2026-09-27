"""Regression tests for the production container logging/startup presentation contract."""

from pathlib import Path

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
    assert "s.overall === \"failed\"" in javascript


def test_detailed_logs_are_not_public_http_resources() -> None:
    startup_nginx = read("../docker-container/nginx/startup.conf")
    ready_nginx = read("../docker-container/nginx/ready.conf")

    assert "/_startup/backend.log" not in startup_nginx
    assert "/_startup/migration.log" not in startup_nginx
    assert "/_startup/backend.log" not in ready_nginx
    assert "/_startup/migration.log" not in ready_nginx


def test_entrypoint_keeps_detailed_logs_outside_startup_details() -> None:
    entrypoint = (DOCKER / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'BACKEND_LOG="$STATUS_DIR/backend.log"' in entrypoint
    assert 'MIGRATION_LOG="$STATUS_DIR/migration.log"' in entrypoint
    assert 'cat "$BACKEND_LOG" >> "$DETAILS_FILE"' not in entrypoint
    assert 'cat "$BACKEND_LOG" > "$DETAILS_FILE"' not in entrypoint
    assert "password" not in entrypoint.split('log "', 1)[-1].split('"', 1)[0].lower()
    assert "SECRET_KEY" not in entrypoint.split('log "', 1)[-1].split('"', 1)[0]


def test_nginx_errors_are_sent_to_container_stderr() -> None:
    for path in ("nginx/startup.conf", "nginx/ready.conf"):
        assert "error_log /dev/stderr warn;" in read(path)


def test_startup_status_contract_contains_failure_states() -> None:
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
