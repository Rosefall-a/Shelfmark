from cryptography.fernet import Fernet
import pytest

from src.core.env_handler import EnvConfigHandler
from src.core.fernet_key import persistent_fernet_key


@pytest.fixture(autouse=True)
def isolated_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SECRET_KEY", raising=False)


def test_database_components_are_resolved():
    handler = EnvConfigHandler({
        "POSTGRES_USER": "archive",
        "POSTGRES_PASSWORD": "secret",
        "POSTGRES_DB": "archive",
    })
    values = handler.resolved()
    assert values["POSTGRES_USER"] == "archive"
    assert values["POSTGRES_DB"] == "archive"


def test_partial_database_configuration_is_unrecoverable():
    handler = EnvConfigHandler({"POSTGRES_USER": "archive"})
    issue = next(issue for issue in handler.validate() if issue.name == "database")
    assert issue.severity == "error"
    assert issue.recoverable is False


def test_partial_primary_user_configuration_is_unrecoverable():
    handler = EnvConfigHandler({
        "PRIMARY_USER_USERNAME": "admin",
        "PRIMARY_USER_EMAIL": "admin@example.com",
    })
    issue = next(issue for issue in handler.validate() if issue.name == "primary_user")
    assert issue.severity == "error"
    assert issue.recoverable is False


def test_partial_oidc_environment_configuration_does_not_enable_validation():
    handler = EnvConfigHandler({
        "OIDC_ISSUER_URL": "https://login.example.test",
        "OIDC_CLIENT_ID": "client",
    })
    assert not any(issue.name == "oidc" and issue.severity == "error" for issue in handler.validate())


def test_oidc_missing_recommended_scope_is_warning():
    handler = EnvConfigHandler({
        "OIDC_ISSUER_URL": "https://login.example.test",
        "OIDC_CLIENT_ID": "client",
        "OIDC_CLIENT_SECRET": "secret",
        "OIDC_SCOPES": "openid",
    })
    issue = next(issue for issue in handler.validate() if issue.name == "oidc" and issue.severity == "warning")
    assert "profile" in issue.message
    assert "email" in issue.message



def test_setup_schema_marks_environment_fields_locked_and_partial():
    handler = EnvConfigHandler({
        "POSTGRES_USER": "archive",
        "POSTGRES_PASSWORD": "secret",
        "POSTGRES_DB": "archive",
        "OIDC_ISSUER_URL": "https://login.example.test",
        "OIDC_CLIENT_ID": "client",
    })
    sections = {section["id"]: section for section in handler.setup_schema()}
    assert sections["database"]["status"] == "completed_by_env"
    assert sections["oidc"]["status"] == "partial"

    issuer = next(field for field in sections["oidc"]["fields"] if field["name"] == "OIDC_ISSUER_URL")
    secret = next(field for field in sections["oidc"]["fields"] if field["name"] == "OIDC_CLIENT_SECRET")
    assert issuer["locked"] is True
    assert issuer["value"] == "https://login.example.test"
    assert secret["locked"] is False
    assert secret["value"] is None


def test_fernet_key_is_generated_and_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SECRET_KEY", raising=False)

    key = persistent_fernet_key()

    assert Fernet(key.encode())
    assert (tmp_path / "config" / "fernet.key").read_text(encoding="utf-8").strip() == key
    assert (tmp_path / "config" / "fernet.key.1").read_text(encoding="utf-8").strip() == key
    assert (tmp_path / "config" / "fernet.key.2").read_text(encoding="utf-8").strip() == key


def test_legacy_database_url_is_only_a_warning():
    handler = EnvConfigHandler({
        "DATABASE_URL": "postgresql+psycopg://archive:secret@db:5432/archive"
    })
    issue = next(issue for issue in handler.validate() if issue.name == "database")
    assert issue.severity == "warning"


def test_env_only_frontend_value_is_not_exposed_to_setup():
    handler = EnvConfigHandler({"VITE_USE_MOCK_DATA": "true"})
    assert all(
        field["name"] != "VITE_USE_MOCK_DATA"
        for section in handler.setup_schema()
        for field in section["fields"]
    )


def test_env_only_required_fields_block_setup_and_are_marked():
    handler = EnvConfigHandler({"POSTGRES_USER": "archive"})
    sections = {section["id"]: section for section in handler.setup_schema()}
    database = sections["database"]
    assert database["blocked"] is True
    assert database["status"] == "blocked_by_env"
    assert "POSTGRES_PASSWORD" in database["blocked_message"]
    password = next(field for field in database["fields"] if field["name"] == "POSTGRES_PASSWORD")
    assert password["env_only"] is True
    assert password["visible"] is False


def test_env_owned_non_secret_values_remain_visible_and_locked():
    handler = EnvConfigHandler({
        "POSTGRES_USER": "archive",
        "POSTGRES_PASSWORD": "secret",
        "POSTGRES_DB": "archive",
        "AUTH_COOKIE_SECURE": "true",
    })
    fields = {
        field["name"]: field
        for section in handler.setup_schema()
        for field in section["fields"]
    }
    assert fields["AUTH_COOKIE_SECURE"]["value"] is True
    assert fields["AUTH_COOKIE_SECURE"]["visible"] is True
    assert fields["AUTH_COOKIE_SECURE"]["locked"] is True


def test_deprecated_setting_exposes_replacement_message():
    handler = EnvConfigHandler({"DATABASE_URL": "postgresql+psycopg://archive:secret@db/archive"})
    field = next(
        field for section in handler.setup_schema() for field in section["fields"]
        if field["name"] == "DATABASE_URL"
    )
    assert field["deprecated_message"] == (
        "DATABASE_URL is deprecated; use POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB instead."
    )



def test_database_url_satisfies_required_database_group():
    handler = EnvConfigHandler({
        "DATABASE_URL": "postgresql+psycopg://archive:secret@db:5432/archive",
    })
    assert not any(issue.name == "database" and issue.severity == "error" for issue in handler.validate())


def test_database_url_satisfies_group_even_with_partial_postgres_components():
    handler = EnvConfigHandler({
        "POSTGRES_USER": "archive",
        "DATABASE_URL": "postgresql+psycopg://archive:secret@db:5432/archive",
    })
    assert not any(issue.name == "database" and issue.severity == "error" for issue in handler.validate())


def test_required_group_metadata_is_exposed_to_generated_schema():
    handler = EnvConfigHandler({
        "POSTGRES_USER": "archive",
        "POSTGRES_PASSWORD": "secret",
        "POSTGRES_DB": "archive",
    })
    database = next(section for section in handler.setup_schema() if section["id"] == "database")
    groups = {field["name"]: field["required_group"] for field in database["fields"]}
    assert groups["POSTGRES_USER"] == "database:postgres"
    assert groups["POSTGRES_PASSWORD"] == "database:postgres"
    assert groups["POSTGRES_DB"] == "database:postgres"
    assert groups["DATABASE_URL"] == "database:url"


def test_default_selected_section_is_exposed_and_required_sections_override_it():
    sections = {section["id"]: section for section in EnvConfigHandler({}).setup_schema()}
    assert all(field["name"] != "OIDC_ENABLED" for field in sections["oidc"]["fields"])
    assert sections["first_admin"]["default"] is True
    assert sections["api_keys"]["default"] is False


def test_generated_values_are_exposed_as_locked_setup_fields():
    handler = EnvConfigHandler()
    sections = {section["id"]: section for section in handler.setup_schema(
        generated_values={"OIDC_REDIRECT_URI": "https://archive.example/api/auth/oidc/callback"}
    )}
    redirect = next(field for field in sections["oidc"]["fields"] if field["name"] == "OIDC_REDIRECT_URI")
    assert redirect["value"] == "https://archive.example/api/auth/oidc/callback"
    assert redirect["source"] == "generated"
    assert redirect["generated"] is True
    assert redirect["locked"] is True


def test_field_headings_are_exposed():
    handler = EnvConfigHandler()
    general = next(section for section in handler.setup_schema() if section["id"] == "general")
    fields = {field["name"]: field for field in general["fields"]}
    assert fields["DEBUG"]["heading"] == "Debug mode"
    assert fields["MAX_UPLOAD_SIZE_MB"]["heading"] == "Max sizes"
    assert fields["MAX_SAVE_ARCHIVE_SIZE_MB"]["heading"] == "Max sizes"


def test_startup_mode_controls_ui_and_development_defaults():
    development = EnvConfigHandler({"STARTUP_MODE": "dev"})
    assert development.mode.value == "development"
    assert development.startup_ui_enabled() is False
    assert development.get("DEBUG") is True
    assert development.get("PRIMARY_USER_USERNAME") == "admin"


def test_testing_mode_shows_ui_and_falls_back_to_development_defaults():
    testing = EnvConfigHandler({"STARTUP_MODE": "testing"})
    assert testing.mode.value == "testing"
    assert testing.startup_ui_enabled() is True
    assert testing.get("DEBUG") is True
    assert testing.get("PRIMARY_USER_PASSWORD") == "Change-this-during-setup"


def test_normal_mode_shows_ui_and_uses_normal_defaults():
    normal = EnvConfigHandler({"STARTUP_MODE": ""})
    assert normal.startup_ui_enabled() is True
    assert normal.get("DEBUG") is False
    assert normal.get("PRIMARY_USER_USERNAME") == "admin"


def test_unknown_startup_mode_uses_normal_mode():
    normal = EnvConfigHandler({"STARTUP_MODE": "something-else"})
    assert normal.mode.value == "default"
    assert normal.startup_ui_enabled() is True
    assert normal.get("DEBUG") is False


def test_environment_values_override_mode_defaults():
    handler = EnvConfigHandler({
        "STARTUP_MODE": "dev",
        "DEBUG": "false",
        "PRIMARY_USER_USERNAME": "developer",
    })
    assert handler.get("DEBUG") is False
    assert handler.get("PRIMARY_USER_USERNAME") == "developer"
