from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.db.database import UnsafeRuntimeRole, assert_runtime_role
from app.identity.api import LoginBody
from app.identity.permissions import ROLE_PERMISSIONS, allowed
from app.identity.security import (
    HASHER,
    TOKEN_PATTERN,
    hash_password,
    new_token,
    token_digest,
    verify_password,
)
from app.main import create_app

TEST_PASSWORD = "Testing only long password 2026!"


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(TEST_PASSWORD)


def test_argon2id_password_roundtrip_and_mismatch(password_hash):
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, TEST_PASSWORD)
    assert not verify_password(password_hash, "incorrect")
    assert not HASHER.check_needs_rehash(password_hash)


def test_missing_or_corrupt_password_fails_closed():
    assert not verify_password(None, TEST_PASSWORD)
    assert not verify_password("not-a-password-hash", TEST_PASSWORD)


@pytest.mark.parametrize("password", ["short", "x" * 1025])
def test_new_password_bounds(password):
    with pytest.raises(ValueError):
        hash_password(password)


def test_session_tokens_are_random_and_only_the_digest_is_stored():
    tokens = {new_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(TOKEN_PATTERN.fullmatch(token) for token in tokens)
    assert all(len(token_digest(token)) == 64 and token_digest(token) != token for token in tokens)


@pytest.mark.parametrize("role", list(ROLE_PERMISSIONS))
def test_only_admin_can_manage_memberships(role):
    assert allowed(role, "memberships.manage") == (role == "admin")


@pytest.mark.parametrize(
    "permission",
    [
        "questions.write",
        "questions.review",
        "exams.manage",
        "scripts.mark",
        "results.publish",
        "memberships.manage",
    ],
)
def test_candidate_cannot_author_review_grade_publish_or_administer(permission):
    assert not allowed("candidate", permission)


def test_unknown_roles_and_permissions_fail_closed():
    assert not allowed("superuser", "memberships.manage")
    assert not allowed("admin", "arbitrary.permission")


def test_role_definitions_cannot_be_modified():
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS["candidate"] = frozenset({"memberships.manage"})


@pytest.mark.parametrize("role_safe,rls_safe", [(False, True), (True, False)])
def test_unsafe_database_role_or_missing_row_security_is_rejected(role_safe, rls_safe):
    connection = MagicMock()
    connection.scalar.side_effect = [role_safe, rls_safe]
    with pytest.raises(UnsafeRuntimeRole):
        assert_runtime_role(connection)


def test_migration_url_falls_back_but_can_be_separated():
    runtime = "postgresql+psycopg://runtime:private@localhost/assessment"
    migration = "postgresql+psycopg://owner:private@localhost/assessment"
    settings = Settings(_env_file=None, database_url=runtime, migration_database_url=migration)
    assert settings.migration_url.get_secret_value() == migration
    assert settings.database_url.get_secret_value() == runtime
    assert "private" not in repr(settings)


def test_windows_bom_configuration_loads(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSESSMENT_DATABASE_URL", raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "ASSESSMENT_DATABASE_URL=postgresql+psycopg://local@localhost/assessment\n", encoding="utf-8-sig"
    )
    assert Settings(_env_file=path).database_url.get_secret_value().endswith("/assessment")


@pytest.fixture
def api_client():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://local@127.0.0.1:1/unavailable",
        database_connect_timeout=1,
    )
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/v1/auth/me", None),
        ("GET", "/api/v1/auth/institutions", None),
        ("POST", "/api/v1/auth/logout", None),
        (
            "POST",
            "/api/v1/auth/change-password",
            {"current_password": "wrong", "new_password": TEST_PASSWORD},
        ),
        ("GET", f"/api/v1/tenants/{uuid4()}/access", None),
        ("GET", f"/api/v1/tenants/{uuid4()}/memberships", None),
        ("POST", f"/api/v1/tenants/{uuid4()}/memberships", {"user_id": str(uuid4())}),
        ("PATCH", f"/api/v1/tenants/{uuid4()}/memberships/{uuid4()}", {"role": "admin"}),
    ],
)
def test_protected_routes_require_authentication_without_touching_database(api_client, method, path, body):
    response = api_client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_bearer_is_rejected_before_database_query(api_client):
    response = api_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer bad-token"})
    assert response.status_code == 401


def test_login_validation_does_not_echo_password(api_client):
    password = "do-not-echo-this" * 100
    response = api_client.post(
        "/api/v1/auth/login", json={"email": "valid@example.test", "password": password}
    )
    assert response.status_code == 422
    assert "do-not-echo-this" not in response.text
    assert "input" not in response.text


def test_login_identity_is_normalized_without_normalizing_password():
    body = LoginBody(email="  USER@example.test ", password=" preserve spaces ")
    assert body.email == "user@example.test"
    assert body.password.get_secret_value() == " preserve spaces "


def test_unreachable_database_login_fails_without_connection_details(api_client):
    response = api_client.post(
        "/api/v1/auth/login", json={"email": "valid@example.test", "password": TEST_PASSWORD}
    )
    assert response.status_code == 503
    assert "127.0.0.1" not in response.text


def test_membership_input_rejects_injected_tenant_or_global_privilege_fields():
    from app.identity.api import MembershipCreate

    with pytest.raises(ValidationError):
        MembershipCreate(user_id=uuid4(), role="candidate", tenant_id=uuid4(), is_platform_admin=True)


def test_runtime_configuration_preserves_original_bom_file_and_other_settings(tmp_path):
    from dotenv import dotenv_values

    from app.manage import configure_env

    path = tmp_path / ".env"
    original = "ASSESSMENT_DATABASE_URL=postgresql+psycopg://owner:private@localhost/assessment\nOTHER_SETTING=preserved\n".encode(
        "utf-8-sig"
    )
    path.write_bytes(original)
    migration = "postgresql+psycopg://owner:private@localhost/assessment"
    runtime = "postgresql+psycopg://assessment_runtime:private@localhost/assessment"
    configure_env(path, migration, runtime)
    values = dotenv_values(path, encoding="utf-8-sig")
    assert values["ASSESSMENT_DATABASE_URL"] == runtime
    assert values["ASSESSMENT_MIGRATION_DATABASE_URL"] == migration
    assert values["OTHER_SETTING"] == "preserved"
    assert (tmp_path / ".env.pre-p1-003").read_bytes() == original


def test_failed_runtime_configuration_keeps_original_file(tmp_path, monkeypatch):
    from app import manage

    path = tmp_path / ".env"
    original = b"ASSESSMENT_DATABASE_URL=original\n"
    path.write_bytes(original)

    def fail_replace(*args):
        raise OSError("simulated write failure")

    monkeypatch.setattr(manage.os, "replace", fail_replace)
    with pytest.raises(OSError):
        manage.configure_env(path, "migration", "runtime")
    assert path.read_bytes() == original
    assert list(tmp_path.glob(".env.runtime-*")) == []
