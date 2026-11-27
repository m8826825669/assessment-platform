"""SCH-01/TEN-01/GOV-01 publication-bound schedules and atomic registrations."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from test_question_review import approve, context, create, path, prepare, submit

from app.db.models import Membership, User

pytestmark = pytest.mark.integration


@pytest.fixture
def sitting_setup(security_database):
    db = security_database
    author, reviewer, coordinator = prepare(db)
    question = approve(db, reviewer, submit(db, author, create(db, author)))
    identity = uuid4()
    draft_url = path(db, "exam-blueprints", f"/drafts/{identity}")
    response = db.client.put(
        draft_url,
        headers=coordinator,
        json={"sections": [{"version_ids": [question["version_id"]], "minimum": 1, "maximum": 1}]},
    )
    assert response.status_code == 200, response.text
    publication = db.client.post(draft_url + "/publish", headers=coordinator)
    assert publication.status_code == 200, publication.text
    candidates = [uuid4(), uuid4()]
    with db.admin_engine.begin() as connection:
        context(connection, db)
        for candidate in candidates:
            connection.execute(
                User.__table__.insert().values(
                    id=candidate,
                    email=candidate.hex + "@example.test",
                    display_name="Synthetic candidate",
                    password_hash=connection.scalar(
                        select(User.password_hash).where(User.id == db.ids["admin_a"])
                    ),
                )
            )
            connection.execute(
                Membership.__table__.insert().values(
                    id=uuid4(),
                    tenant_id=db.ids["tenant_a"],
                    user_id=candidate,
                    role="candidate",
                )
            )
    start = datetime.now(UTC) + timedelta(days=1)
    body = {
        "publication_id": str(identity),
        "title": "Grammar sitting",
        "opens_at": start.isoformat(),
        "closes_at": (start + timedelta(hours=2)).isoformat(),
        "display_timezone": "UTC+05:30",
    }
    sitting_id = uuid4()
    url = path(db, "exam-sittings", f"/{sitting_id}")
    return db, coordinator, reviewer, candidates, url, body


def schedule(setup):
    db, coordinator, _, _, url, body = setup
    response = db.client.put(url, headers=coordinator, json=body)
    assert response.status_code == 200, response.text
    return response


def registration(candidate, *, extra=0):
    return {
        "id": str(uuid4()),
        "candidate_user_id": str(candidate),
        "extra_minutes": extra,
        **({"accommodation_reason": "Approved extra time"} if extra else {}),
    }


def test_schedule_snapshot_retry_conflict_and_list(sitting_setup):
    db, coordinator, _, _, url, body = sitting_setup
    saved = schedule(sitting_setup)
    assert saved.json()["publication_id"] == body["publication_id"]
    assert saved.json()["duration_minutes"] == saved.json()["policy"]["duration_minutes"] == 30
    assert db.client.put(url, headers=coordinator, json=body).json() == saved.json()
    assert db.client.put(url, headers=coordinator, json={**body, "title": "Changed"}).status_code == 409
    assert db.client.get(url, headers=coordinator).json() == saved.json()
    listing = db.client.get(path(db, "exam-sittings"), headers=coordinator)
    assert listing.status_code == 200 and len(listing.json()) == 1
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert (
            connection.scalar(text("SELECT count(*) FROM audit_records WHERE action='exam.sitting_created'"))
            == 1
        )


def test_atomic_registration_import_extra_time_and_replay(sitting_setup):
    db, coordinator, _, candidates, url, body = sitting_setup
    schedule(sitting_setup)
    batch = {"registrations": [registration(candidates[0]), registration(candidates[1], extra=20)]}
    response = db.client.post(url + "/registrations", headers=coordinator, json=batch)
    assert response.status_code == 200, response.text
    assert [row["allowed_minutes"] for row in response.json()] == [30, 50]
    assert db.client.post(url + "/registrations", headers=coordinator, json=batch).json() == response.json()
    changed = {
        "registrations": [
            {**batch["registrations"][0], "extra_minutes": 10, "accommodation_reason": "Changed allowance"}
        ]
    }
    assert db.client.post(url + "/registrations", headers=coordinator, json=changed).status_code == 409
    assert len(db.client.get(url + "/registrations", headers=coordinator).json()) == 2
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM audit_records WHERE action='exam.candidate_registered'")
            )
            == 2
        )


def test_invalid_candidate_import_is_atomic(sitting_setup):
    db, coordinator, _, candidates, url, body = sitting_setup
    schedule(sitting_setup)
    batch = {"registrations": [registration(candidates[0]), registration(uuid4())]}
    assert db.client.post(url + "/registrations", headers=coordinator, json=batch).status_code == 409
    assert db.client.get(url + "/registrations", headers=coordinator).json() == []


@pytest.mark.parametrize("operation", ["sitting", "registration"])
@pytest.mark.parametrize("table", ["audit_records", "outbox_events", "outbox_deliveries"])
def test_schedule_and_registration_rollback(sitting_setup, operation, table):
    db, coordinator, _, candidates, url, body = sitting_setup
    if operation == "registration":
        schedule(sitting_setup)
    engine = db.client.app.state.database.engine

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith("INSERT INTO " + table):
            raise SQLAlchemyError("Injected sitting transaction failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = (
            db.client.put(url, headers=coordinator, json=body)
            if operation == "sitting"
            else db.client.post(
                url + "/registrations",
                headers=coordinator,
                json={"registrations": [registration(candidates[0])]},
            )
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503, response.text
    if operation == "sitting":
        assert db.client.get(url, headers=coordinator).status_code == 404
    else:
        assert db.client.get(url + "/registrations", headers=coordinator).json() == []
    action = "exam.sitting_created" if operation == "sitting" else "exam.candidate_registered"
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM audit_records WHERE action=:action"), {"action": action}
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM outbox_events WHERE payload->>'action'=:action"),
                {"action": action},
            )
            == 0
        )


def test_concurrent_registration_retries_do_not_duplicate(sitting_setup):
    db, coordinator, _, candidates, url, body = sitting_setup
    schedule(sitting_setup)
    batch = {"registrations": [registration(candidates[0])]}
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: db.client.post(url + "/registrations", headers=coordinator, json=batch), range(2)
            )
        )
    assert [response.status_code for response in results] == [200, 200]
    assert results[0].json() == results[1].json()
    assert len(db.client.get(url + "/registrations", headers=coordinator).json()) == 1


def test_wrong_role_and_tenant_cannot_schedule(sitting_setup):
    db, coordinator, reviewer, _, url, body = sitting_setup
    assert db.client.put(url, headers=reviewer, json=body).status_code == 403
    foreign = url.replace(str(db.ids["tenant_a"]), str(db.ids["tenant_b"]))
    assert db.client.put(foreign, headers=coordinator, json=body).status_code == 404
    assert (
        db.client.put(url, headers=coordinator, json={**body, "publication_id": str(uuid4())}).status_code
        == 404
    )


def test_accommodation_must_fit_and_inactive_candidate_is_denied(sitting_setup):
    db, coordinator, _, candidates, url, body = sitting_setup
    body["closes_at"] = (datetime.fromisoformat(body["opens_at"]) + timedelta(minutes=30)).isoformat()
    schedule(sitting_setup)
    assert (
        db.client.post(
            url + "/registrations",
            headers=coordinator,
            json={"registrations": [registration(candidates[0], extra=1)]},
        ).status_code
        == 409
    )
    with db.admin_engine.begin() as connection:
        connection.execute(update(User).where(User.id == candidates[0]).values(is_active=False))
    assert (
        db.client.post(
            url + "/registrations", headers=coordinator, json={"registrations": [registration(candidates[0])]}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("table", ["exam_sittings", "sitting_registrations"])
def test_direct_sql_snapshots_are_immutable(sitting_setup, table):
    db, coordinator, _, candidates, url, body = sitting_setup
    schedule(sitting_setup)
    row = registration(candidates[0])
    assert (
        db.client.post(url + "/registrations", headers=coordinator, json={"registrations": [row]}).status_code
        == 200
    )
    with pytest.raises(DBAPIError):
        with db.admin_engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {table}"))


@pytest.mark.parametrize(
    "trigger,table",
    [("exam_sitting_guard", "exam_sittings"), ("sitting_registration_guard", "sitting_registrations")],
)
def test_readiness_requires_scheduling_guards(security_database, trigger, table):
    db = security_database
    with db.admin_engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["runtime_role"] == "unsafe"


def test_candidate_eligibility_and_direct_sql_isolation(sitting_setup):
    db, coordinator, _, candidates, url, body = sitting_setup
    schedule(sitting_setup)
    first = db.login(candidates[0].hex)
    second = db.login(candidates[1].hex)
    assert db.client.get(url + "/eligibility", headers=first).status_code == 404
    rows = [registration(candidates[0], extra=15), registration(candidates[1])]
    assert (
        db.client.post(url + "/registrations", headers=coordinator, json={"registrations": rows}).status_code
        == 200
    )
    response = db.client.get(url + "/eligibility", headers=first)
    assert response.status_code == 200, response.text
    assert response.json()["allowed_minutes"] == 45
    assert response.json()["window_state"] == "upcoming" and response.json()["can_start"] is False
    assert response.json()["deadline_if_started_now"] is None
    assert set(response.json()) == {
        "sitting_id",
        "publication_id",
        "title",
        "registration_id",
        "allowed_minutes",
        "opens_at",
        "closes_at",
        "display_timezone",
        "window_state",
        "can_start",
        "server_time",
        "deadline_if_started_now",
    }
    assert db.client.get(url + "/registrations", headers=first).status_code == 403
    assert db.client.get(url + "/eligibility", headers=second).json()["allowed_minutes"] == 30
    db.ids["registered"] = candidates[0]
    with db.runtime_engine.begin() as connection:
        context(connection, db, "registered")
        assert connection.scalars(text("SELECT candidate_user_id FROM sitting_registrations")).all() == [
            candidates[0]
        ]
        assert connection.scalar(text("SELECT count(*) FROM exam_sittings")) == 1
        assert connection.scalar(text("SELECT count(*) FROM exam_publications")) == 0
    with db.admin_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            update(Membership)
            .where(Membership.tenant_id == db.ids["tenant_a"], Membership.user_id == candidates[0])
            .values(status="suspended")
        )
    assert db.client.get(url + "/eligibility", headers=first).status_code == 404
    with db.runtime_engine.begin() as connection:
        context(connection, db, "registered")
        assert connection.scalar(text("SELECT count(*) FROM exam_sittings")) == 0
        assert connection.scalar(text("SELECT count(*) FROM sitting_registrations")) == 0


def test_foreign_tenant_direct_sql_cannot_read_or_insert_sitting(sitting_setup):
    db, coordinator, _, candidates, url, body = sitting_setup
    schedule(sitting_setup)
    with db.runtime_engine.begin() as connection:
        context(connection, db, "admin_b", tenant="b")
        assert connection.scalar(text("SELECT count(*) FROM exam_sittings")) == 0
        assert connection.scalar(text("SELECT count(*) FROM sitting_registrations")) == 0
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as connection:
            context(connection, db, "admin_b", tenant="b")
            connection.execute(
                text(
                    "INSERT INTO exam_sittings(tenant_id,id,publication_id,title,opens_at,closes_at,display_timezone,"
                    "duration_minutes,policy,created_by) VALUES(:foreign,:id,:pub,'Foreign',:opens,:closes,'UTC',30,"
                    "jsonb_build_object('duration_minutes',30),:actor)"
                ),
                {
                    "foreign": db.ids["tenant_a"],
                    "id": uuid4(),
                    "pub": UUID(body["publication_id"]),
                    "opens": datetime.fromisoformat(body["opens_at"]),
                    "closes": datetime.fromisoformat(body["closes_at"]),
                    "actor": db.ids["admin_b"],
                },
            )


@pytest.mark.parametrize("table", ["exam_sittings", "sitting_registrations"])
def test_worker_has_no_scheduling_read_privilege(outbox_database, table):
    db = outbox_database
    with pytest.raises(DBAPIError):
        with db.worker_database.engine.begin() as connection:
            connection.execute(text(f"SELECT * FROM {table}"))


def test_sitting_keeps_exact_publication_after_later_draft_edit(sitting_setup):
    db, coordinator, _, candidates, url, body = sitting_setup
    original = schedule(sitting_setup).json()
    root = path(db, "exam-blueprints", f"/drafts/{body['publication_id']}")
    revision = db.client.post(
        root + "/revisions",
        headers=coordinator,
        json={"id": str(uuid4()), "expected_revision": 1, "sections": []},
    )
    assert revision.status_code == 200, revision.text
    assert db.client.get(url, headers=coordinator).json() == original
    assert db.client.put(url, headers=coordinator, json=body).json() == original


@pytest.mark.parametrize("table", ["exam_sittings", "sitting_registrations"])
def test_readiness_requires_scheduling_insert_grants(security_database, table):
    import psycopg
    from psycopg import sql

    db = security_database
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL("REVOKE INSERT ON {} FROM {}").format(
                sql.Identifier(table), sql.Identifier(db.runtime_engine.url.username)
            )
        )
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["runtime_role"] == "missing_grants"


def test_candidate_cannot_register_by_direct_sql(sitting_setup):
    db, coordinator, _, candidates, url, body = sitting_setup
    original = schedule(sitting_setup).json()
    db.ids["registered"] = candidates[0]
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as connection:
            context(connection, db, "registered")
            connection.execute(
                text(
                    "INSERT INTO sitting_registrations(tenant_id,id,sitting_id,candidate_user_id,extra_minutes,"
                    "allowed_minutes,created_by) VALUES(:tenant,:id,:sitting,:candidate,0,30,:candidate)"
                ),
                {
                    "tenant": db.ids["tenant_a"],
                    "id": uuid4(),
                    "sitting": UUID(original["id"]),
                    "candidate": candidates[0],
                },
            )
    assert db.client.get(url + "/registrations", headers=coordinator).json() == []


def test_late_batch_outbox_failure_rolls_back_earlier_candidate(sitting_setup):
    db, coordinator, _, candidates, url, body = sitting_setup
    schedule(sitting_setup)
    engine = db.client.app.state.database.engine
    deliveries = 0

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        nonlocal deliveries
        if statement.startswith("INSERT INTO outbox_deliveries"):
            deliveries += 1
            if deliveries == 2:
                raise SQLAlchemyError("Injected late batch failure")

    batch = {"registrations": [registration(candidate) for candidate in candidates]}
    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = db.client.post(url + "/registrations", headers=coordinator, json=batch)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503, response.text
    assert db.client.get(url + "/registrations", headers=coordinator).json() == []
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM audit_records WHERE action='exam.candidate_registered'")
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM outbox_events WHERE payload->>'action'='exam.candidate_registered'"
                )
            )
            == 0
        )
    assert db.client.post(url + "/registrations", headers=coordinator, json=batch).status_code == 200


@pytest.mark.parametrize("table", ["exam_sittings", "sitting_registrations"])
def test_worker_provisioning_refuses_scheduling_privileges(outbox_database, table):
    import psycopg
    from psycopg import sql

    from app.db.provisioning import grant_worker

    db = outbox_database
    role = db.worker_database.engine.url.username
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL("GRANT SELECT ON {} TO {}").format(sql.Identifier(table), sql.Identifier(role))
        )
    with psycopg.connect(dsn) as connection:
        with pytest.raises(ValueError, match="separate"):
            grant_worker(connection, role)
