from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import AuthSession, Institution, Membership, SecurityEvent, User

pytestmark = pytest.mark.integration


def path(database, suffix, resource="access"):
    return f"/api/v1/tenants/{database.ids[f'tenant_{suffix}']}/{resource}"


def tenant_context(connection, tenant_id):
    connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})


def test_runtime_role_and_policies_are_ready(security_database):
    response = security_database.client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["dependencies"] == {"postgresql": "ok", "schema": "ok", "runtime_role": "ok"}


def test_login_me_logout_and_no_plaintext_token_storage(security_database):
    db = security_database
    headers = db.login("admin_a")
    response = db.client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["user_id"] == str(db.ids["admin_a"])
    assert set(response.json()) == {"user_id", "email", "display_name"}
    with Session(db.admin_engine) as session:
        stored = session.scalars(select(AuthSession)).one()
        assert len(stored.token_hash) == 64
        assert stored.token_hash != headers["Authorization"].split()[1]
        assert session.scalar(select(SecurityEvent.action).where(SecurityEvent.action == "login.succeeded"))
    assert db.client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert db.client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_wrong_password_and_unknown_user_have_identical_responses(security_database):
    db = security_database
    responses = [
        db.client.post("/api/v1/auth/login", json={"email": email, "password": "incorrect"})
        for email in ["admin_a@example.test", "unknown@example.test"]
    ]
    assert [response.status_code for response in responses] == [401, 401]
    from uuid import UUID

    payloads = [response.json() for response in responses]
    for response, payload in zip(responses, payloads, strict=True):
        correlation = str(UUID(payload["request_id"]))
        assert response.headers["x-request-id"] == correlation
        assert payload["instance"] == "urn:assessment:request:" + correlation
        assert payload["code"] == "invalid_credentials"
        assert payload["detail"] == "Invalid email or password"
    assert payloads[0]["request_id"] != payloads[1]["request_id"]
    stable = [
        {key: value for key, value in payload.items() if key not in {"request_id", "instance"}}
        for payload in payloads
    ]
    assert stable[0] == stable[1]


def test_failed_login_is_rate_limited_and_recorded(security_database):
    db = security_database
    for _ in range(3):
        assert (
            db.client.post(
                "/api/v1/auth/login", json={"email": "admin_a@example.test", "password": "wrong"}
            ).status_code
            == 401
        )
    response = db.client.post(
        "/api/v1/auth/login", json={"email": "admin_a@example.test", "password": db.password}
    )
    assert response.status_code == 429
    with Session(db.admin_engine) as session:
        assert (
            len(session.scalars(select(SecurityEvent).where(SecurityEvent.action == "login.failed")).all())
            == 3
        )
        assert session.scalar(select(SecurityEvent.id).where(SecurityEvent.action == "login.throttled"))


def test_session_expiry_is_checked_on_every_request(security_database):
    db = security_database
    headers = db.login("admin_a")
    with Session(db.admin_engine) as session, session.begin():
        record = session.scalars(select(AuthSession)).one()
        record.created_at -= timedelta(hours=2)
        record.expires_at = record.created_at + timedelta(hours=1)
    assert db.client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_disabling_user_invalidates_existing_session(security_database):
    db = security_database
    headers = db.login("admin_a")
    with Session(db.admin_engine) as session, session.begin():
        session.get(User, db.ids["admin_a"]).is_active = False
    assert db.client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert (
        db.client.post(
            "/api/v1/auth/login", json={"email": "admin_a@example.test", "password": db.password}
        ).status_code
        == 401
    )


def test_password_change_revokes_all_sessions(security_database):
    db = security_database
    first, second = db.login("admin_a"), db.login("admin_a")
    new_password = "A new long fixture password 2026!"
    response = db.client.post(
        "/api/v1/auth/change-password",
        headers=first,
        json={"current_password": db.password, "new_password": new_password},
    )
    assert response.status_code == 204
    assert db.client.get("/api/v1/auth/me", headers=first).status_code == 401
    assert db.client.get("/api/v1/auth/me", headers=second).status_code == 401
    headers = db.login("admin_a", new_password)
    assert db.client.get("/api/v1/auth/me", headers=headers).status_code == 200


def test_failed_password_change_does_not_revoke_session(security_database):
    db = security_database
    headers = db.login("admin_a")
    response = db.client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": "wrong", "new_password": "New long fixture password!"},
    )
    assert response.status_code == 400
    assert db.client.get("/api/v1/auth/me", headers=headers).status_code == 200


def test_admin_cannot_access_other_institution(security_database):
    db = security_database
    headers = db.login("admin_a")
    assert db.client.get(path(db, "a"), headers=headers).status_code == 200
    assert db.client.get(path(db, "b"), headers=headers).status_code == 404
    assert db.client.get(path(db, "b", "memberships"), headers=headers).status_code == 404
    response = db.client.post(
        path(db, "b", "memberships"),
        headers=headers,
        json={"user_id": str(db.ids["outsider"]), "role": "admin"},
    )
    assert response.status_code == 404


def test_foreign_record_id_cannot_be_modified_under_own_tenant(security_database):
    db = security_database
    headers = db.login("admin_a")
    response = db.client.patch(
        path(db, "a", f"memberships/{db.ids['membership_b']}"), headers=headers, json={"role": "candidate"}
    )
    assert response.status_code == 404
    with Session(db.admin_engine) as session:
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(db.ids["tenant_b"])}
        )
        assert session.get(Membership, db.ids["membership_b"]).role == "admin"


def test_candidate_cannot_list_create_or_promote_memberships(security_database):
    db = security_database
    headers = db.login("candidate")
    assert db.client.get(path(db, "a"), headers=headers).status_code == 200
    assert db.client.get(path(db, "a", "memberships"), headers=headers).status_code == 403
    assert (
        db.client.post(
            path(db, "a", "memberships"),
            headers=headers,
            json={"user_id": str(db.ids["outsider"]), "role": "admin"},
        ).status_code
        == 403
    )
    assert (
        db.client.patch(
            path(db, "a", f"memberships/{db.ids['membership_candidate']}"),
            headers=headers,
            json={"role": "admin"},
        ).status_code
        == 403
    )


def test_last_active_admin_cannot_be_demoted_or_suspended(security_database):
    db = security_database
    headers = db.login("admin_a")
    for body in [{"role": "candidate"}, {"status": "suspended"}]:
        assert (
            db.client.patch(
                path(db, "a", f"memberships/{db.ids['membership_a']}"), headers=headers, json=body
            ).status_code
            == 409
        )


def test_admin_can_add_existing_user_and_changes_are_audited(security_database):
    db = security_database
    headers = db.login("admin_a")
    response = db.client.post(
        path(db, "a", "memberships"),
        headers=headers,
        json={"user_id": str(db.ids["outsider"]), "role": "examiner"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "examiner"
    with Session(db.admin_engine) as session:
        assert session.scalar(select(SecurityEvent.id).where(SecurityEvent.action == "membership.created"))
    outsider_headers = db.login("outsider")
    assert "scripts.mark" in db.client.get(path(db, "a"), headers=outsider_headers).json()["permissions"]


def test_membership_role_changes_apply_to_existing_session(security_database):
    db = security_database
    headers, candidate = db.login("admin_a"), db.login("candidate")
    target = path(db, "a", f"memberships/{db.ids['membership_candidate']}")
    assert db.client.patch(target, headers=headers, json={"role": "reviewer"}).status_code == 200
    response = db.client.get(path(db, "a"), headers=candidate)
    assert response.json()["role"] == "reviewer"
    assert "questions.review" in response.json()["permissions"]
    assert "questions.write" not in response.json()["permissions"]


def test_membership_suspension_applies_to_existing_session(security_database):
    db = security_database
    admin, candidate = db.login("admin_a"), db.login("candidate")
    assert (
        db.client.patch(
            path(db, "a", f"memberships/{db.ids['membership_candidate']}"),
            headers=admin,
            json={"status": "suspended"},
        ).status_code
        == 200
    )
    assert db.client.get(path(db, "a"), headers=candidate).status_code == 404


def test_suspended_institution_denies_access(security_database):
    db = security_database
    headers = db.login("admin_a")
    with db.admin_engine.begin() as connection:
        tenant_context(connection, db.ids["tenant_a"])
        connection.execute(
            update(Institution).where(Institution.id == db.ids["tenant_a"]).values(status="suspended")
        )
    assert db.client.get(path(db, "a"), headers=headers).status_code == 404


def test_institution_picker_only_returns_own_active_memberships(security_database):
    db = security_database
    headers = db.login("admin_a")
    response = db.client.get("/api/v1/auth/institutions", headers=headers)
    assert response.status_code == 200
    assert [row["tenant_id"] for row in response.json()] == [str(db.ids["tenant_a"])]


def test_two_institutions_can_assign_different_roles_to_same_user(security_database):
    db = security_database
    admin_b, candidate = db.login("admin_b"), db.login("candidate")
    assert (
        db.client.post(
            path(db, "b", "memberships"),
            headers=admin_b,
            json={"user_id": str(db.ids["candidate"]), "role": "examiner"},
        ).status_code
        == 201
    )
    assert db.client.get(path(db, "a"), headers=candidate).json()["role"] == "candidate"
    assert db.client.get(path(db, "b"), headers=candidate).json()["role"] == "examiner"
    response = db.client.get("/api/v1/auth/institutions", headers=candidate)
    assert {row["tenant_id"] for row in response.json()} == {str(db.ids["tenant_a"]), str(db.ids["tenant_b"])}


def test_duplicate_membership_is_a_controlled_conflict(security_database):
    db = security_database
    headers = db.login("admin_a")
    response = db.client.post(
        path(db, "a", "memberships"), headers=headers, json={"user_id": str(db.ids["candidate"])}
    )
    assert response.status_code == 409
    assert "constraint" not in response.text.lower()


def test_rls_denies_rows_without_context(security_database):
    with security_database.runtime_engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM institutions")).all() == []
        assert connection.execute(text("SELECT id FROM memberships")).all() == []


def test_rls_scopes_unfiltered_reads_to_current_institution(security_database):
    db = security_database
    with db.runtime_engine.begin() as connection:
        tenant_context(connection, db.ids["tenant_a"])
        rows = connection.execute(text("SELECT tenant_id FROM memberships")).scalars().all()
        assert len(rows) == 2
        assert set(rows) == {db.ids["tenant_a"]}
        assert connection.execute(text("SELECT id FROM institutions")).scalars().all() == [db.ids["tenant_a"]]


def test_rls_does_not_leak_scope_after_transaction(security_database):
    db = security_database
    with db.runtime_engine.connect() as connection:
        with connection.begin():
            tenant_context(connection, db.ids["tenant_a"])
            assert connection.scalar(text("SELECT count(*) FROM memberships")) == 2
        assert connection.scalar(text("SELECT count(*) FROM memberships")) == 0


def test_rls_rejects_cross_tenant_insert(security_database):
    db = security_database
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        tenant_context(connection, db.ids["tenant_a"])
        connection.execute(
            text("INSERT INTO memberships (id, tenant_id, user_id) VALUES (:id, :tenant, :user)"),
            {"id": uuid4(), "tenant": db.ids["tenant_b"], "user": db.ids["outsider"]},
        )


def test_rls_prevents_cross_tenant_update(security_database):
    db = security_database
    with db.runtime_engine.begin() as connection:
        tenant_context(connection, db.ids["tenant_a"])
        result = connection.execute(
            text("UPDATE memberships SET role = :role WHERE id = :id"),
            {"role": "candidate", "id": db.ids["membership_b"]},
        )
        assert result.rowcount == 0


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE forbidden_table (id int)",
        "ALTER TABLE memberships DISABLE ROW LEVEL SECURITY",
        "TRUNCATE memberships",
        "DELETE FROM memberships",
        "UPDATE users SET is_active = false",
        "SELECT * FROM security_events",
        "UPDATE security_events SET action = 'tampered'",
        "DELETE FROM security_events",
    ],
)
def test_runtime_cannot_migrate_delete_or_rewrite_security_history(security_database, statement):
    with pytest.raises(DBAPIError), security_database.runtime_engine.begin() as connection:
        tenant_context(connection, security_database.ids["tenant_a"])
        connection.execute(text(statement))


def test_concurrent_admin_demotions_leave_one_active_admin(security_database):
    from concurrent.futures import ThreadPoolExecutor

    db = security_database
    first = db.login("admin_a")
    response = db.client.post(
        path(db, "a", "memberships"),
        headers=first,
        json={"user_id": str(db.ids["outsider"]), "role": "admin"},
    )
    assert response.status_code == 201
    second_membership = response.json()["id"]
    second = db.login("outsider")
    jobs = [(first, str(db.ids["membership_a"])), (second, second_membership)]

    def demote(job):
        headers, identifier = job
        return db.client.patch(
            path(db, "a", f"memberships/{identifier}"), headers=headers, json={"role": "candidate"}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(demote, jobs)) == [200, 409]
    with db.runtime_engine.begin() as connection:
        tenant_context(connection, db.ids["tenant_a"])
        assert (
            connection.scalar(text("SELECT count(*) FROM memberships WHERE role='admin' AND status='active'"))
            == 1
        )


def test_concurrent_login_attempts_cannot_bypass_throttle(security_database):
    from concurrent.futures import ThreadPoolExecutor

    db = security_database

    def attempt(_):
        return db.client.post(
            "/api/v1/auth/login", json={"email": "unknown@example.test", "password": "wrong"}
        ).status_code

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(attempt, range(5)))
    assert sorted(results) == [401, 401, 401, 429, 429]


def test_migration_owner_is_rejected_for_business_requests(test_database):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    url, _, _, migrate = test_database
    migrate()
    with TestClient(create_app(Settings(_env_file=None, database_url=url))) as client:
        response = client.post(
            "/api/v1/auth/login", json={"email": "any@example.test", "password": "anything"}
        )
        assert response.status_code == 503
        assert response.json()["code"] == "database_not_ready"


def test_disabled_account_does_not_count_as_a_replacement_admin(security_database):
    db = security_database
    admin = db.login("admin_a")
    assert (
        db.client.post(
            path(db, "a", "memberships"),
            headers=admin,
            json={"user_id": str(db.ids["outsider"]), "role": "admin"},
        ).status_code
        == 201
    )
    with Session(db.admin_engine) as session, session.begin():
        session.get(User, db.ids["outsider"]).is_active = False
    response = db.client.patch(
        path(db, "a", f"memberships/{db.ids['membership_a']}"), headers=admin, json={"role": "candidate"}
    )
    assert response.status_code == 409


def test_account_without_credentials_does_not_count_as_replacement_admin(security_database):
    db = security_database
    admin = db.login("admin_a")
    assert (
        db.client.post(
            path(db, "a", "memberships"),
            headers=admin,
            json={"user_id": str(db.ids["outsider"]), "role": "admin"},
        ).status_code
        == 201
    )
    with Session(db.admin_engine) as session, session.begin():
        session.get(User, db.ids["outsider"]).password_hash = None
    response = db.client.patch(
        path(db, "a", f"memberships/{db.ids['membership_a']}"), headers=admin, json={"role": "candidate"}
    )
    assert response.status_code == 409
