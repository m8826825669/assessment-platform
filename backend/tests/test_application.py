import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


def unavailable_settings():
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://probe:never-log-this@127.0.0.1:1/assessment_test",
        database_connect_timeout=1,
    )


def test_liveness_does_not_require_a_database():
    with TestClient(create_app(unavailable_settings())) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "assessment-api"}
    assert response.headers["cache-control"] == "no-store"


def test_readiness_fails_when_database_is_unreachable_without_exposing_credentials():
    with TestClient(create_app(unavailable_settings())) as client:
        response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"] == {
        "postgresql": "unavailable",
        "schema": "unknown",
        "runtime_role": "unknown",
    }
    assert "never-log-this" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_settings_do_not_show_credentials_in_repr():
    assert "never-log-this" not in repr(unavailable_settings())


@pytest.mark.parametrize("url", ["sqlite:///example.db", "postgresql://user@localhost/test", "invalid"])
def test_non_supported_database_configuration_is_rejected(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


def test_unconfigured_application_fails_closed(monkeypatch):
    monkeypatch.delenv("ASSESSMENT_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_documented_identity_and_institution_endpoints_are_exposed():
    app = create_app(unavailable_settings())
    paths = app.openapi()["paths"]
    assert set(paths) == {
        "/api/v1/tenants/{tenant_id}/questions",
        "/api/v1/tenants/{tenant_id}/questions/{question_id}",
        "/api/v1/tenants/{tenant_id}/questions/{question_id}/versions",
        "/api/v1/tenants/{tenant_id}/questions/{question_id}/versions/{version_id}",
        "/api/v1/tenants/{tenant_id}/questions/{question_id}/preview",
        "/api/v1/tenants/{tenant_id}/question-reviews",
        "/api/v1/tenants/{tenant_id}/question-reviews/{question_id}/versions/{version_id}",
        "/api/v1/tenants/{tenant_id}/question-reviews/{question_id}/versions/{version_id}/preview",
        "/api/v1/tenants/{tenant_id}/question-selections",
        "/api/v1/tenants/{tenant_id}/question-selections/{version_id}",
        "/api/v1/tenants/{tenant_id}/taxonomy",
        "/api/v1/tenants/{tenant_id}/taxonomy/{term_id}",
        "/api/v1/tenants/{tenant_id}/media",
        "/api/v1/tenants/{tenant_id}/media/{asset_id}",
        "/api/v1/tenants/{tenant_id}/media/{asset_id}/content",
        "/api/v1/tenants/{tenant_id}/media/{asset_id}/scan",
        "/api/v1/tenants/{tenant_id}/question-imports",
        "/api/v1/tenants/{tenant_id}/question-imports/preview",
        "/api/v1/tenants/{tenant_id}/question-imports/{batch_id}",
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/auth/change-password",
        "/api/v1/auth/institutions",
        "/api/v1/tenants/{tenant_id}/access",
        "/api/v1/tenants/{tenant_id}/audit",
        "/api/v1/tenants/{tenant_id}/memberships",
        "/api/v1/tenants/{tenant_id}/memberships/{membership_id}",
    }
    app.state.database.close()


@pytest.mark.parametrize(
    "revisions,tables_exist,expected",
    [
        (["0008_question_imports"], True, "ok"),
        ([], True, "not_ready"),
        (["old_revision"], True, "not_ready"),
        (["0008_question_imports", "other_branch"], True, "not_ready"),
        (["0008_question_imports"], False, "not_ready"),
    ],
)
def test_schema_readiness_decisions(revisions, tables_exist, expected):
    from unittest.mock import MagicMock

    from app.db.database import Database

    database = Database(unavailable_settings())
    database.engine.dispose()
    database.engine = MagicMock()
    connection = database.engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalars.return_value = iter(revisions)
    connection.scalar.return_value = tables_exist
    assert database.readiness() == {
        "postgresql": "ok",
        "schema": expected,
        "runtime_role": "ok" if expected == "ok" else "unknown",
    }


def test_schema_probe_failure_is_not_reported_as_database_outage():
    from unittest.mock import MagicMock

    from sqlalchemy.exc import SQLAlchemyError

    from app.db.database import Database

    database = Database(unavailable_settings())
    database.engine.dispose()
    database.engine = MagicMock()
    connection = database.engine.connect.return_value.__enter__.return_value
    connection.execute.side_effect = [None, SQLAlchemyError("schema missing")]
    assert database.readiness() == {"postgresql": "ok", "schema": "not_ready", "runtime_role": "unknown"}


def test_readiness_reports_missing_audit_outbox_grants():
    from unittest.mock import MagicMock

    from app.db.database import Database

    database = Database(unavailable_settings())
    database.engine.dispose()
    database.engine = MagicMock()
    connection = database.engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalars.return_value = iter(["0008_question_imports"])
    connection.scalar.side_effect = [True, True, True, False]
    assert database.readiness() == {"postgresql": "ok", "schema": "ok", "runtime_role": "missing_grants"}
