from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def app():
    return create_app(
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://local:must-not-echo@127.0.0.1:1/disposable",
            database_connect_timeout=1,
        )
    )


@pytest.mark.parametrize(
    "method,path,body,expected,code",
    [
        ("GET", "/api/v1/auth/me", None, 401, "invalid_session"),
        ("GET", "/not-a-route", None, 404, "http_404"),
        ("POST", "/api/v1/health", None, 405, "http_405"),
        ("POST", "/api/v1/auth/login", {}, 422, "validation_error"),
        (
            "POST",
            "/api/v1/auth/login",
            {"email": "valid@example.test", "password": "test"},
            503,
            "database_not_ready",
        ),
    ],
)
def test_all_error_classes_use_problem_details_and_correlation(app, method, path, body, expected, code):
    with TestClient(app) as client:
        response = client.request(method, path, json=body, headers={"X-Request-ID": "caller-supplied"})
    assert response.status_code == expected
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["status"] == expected
    assert payload["code"] == code
    assert str(UUID(payload["request_id"])) == response.headers["x-request-id"]
    assert payload["instance"] == "urn:assessment:request:" + payload["request_id"]
    assert "must-not-echo" not in response.text
    assert "caller-supplied" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_validation_error_excludes_password_and_query_token(app):
    secret = "never-return-this-value" * 100
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login?token=hidden-query-value", json={"email": "invalid", "password": secret}
        )
    assert response.status_code == 422
    assert "never-return-this-value" not in response.text
    assert "hidden-query-value" not in response.text
    assert all(set(field) == {"location", "code", "message"} for field in response.json()["errors"])


def test_unhandled_error_is_generic_and_does_not_log_exception_message(app, caplog):
    @app.get("/test-fault")
    def fault():
        raise RuntimeError("secret-exception-content")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test-fault")
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "secret-exception-content" not in response.text
    assert "secret-exception-content" not in caplog.text
    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_openapi_documents_problem_media_and_readiness_exception(app):
    schema = app.openapi()
    login_error = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]["422"]["content"]
    assert set(login_error) == {"application/problem+json"}
    ready_error = schema["paths"]["/api/v1/ready"]["get"]["responses"]["503"]["content"]
    assert ready_error["application/json"]["schema"]["$ref"].endswith("/Readiness")
    app.state.database.close()
