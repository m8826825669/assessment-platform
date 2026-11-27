"""SCH-01/TEN-01/GOV-01 cancellation transaction boundaries."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
import test_exam_sittings
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from test_exam_sittings import registration, schedule
from test_question_review import context

pytestmark = pytest.mark.integration
BODY = {"reason_code": "administrative"}


@pytest.fixture
def sitting_setup(security_database):
    return test_exam_sittings.sitting_setup.__wrapped__(security_database)


def cancel(setup, body=None):
    db, staff, _, _, url, _ = setup
    return db.client.put(url + "/cancellation", headers=staff, json=body or BODY)


def test_cancellation_retry_and_preserved_snapshots(sitting_setup):
    db, staff, _, candidates, url, body = sitting_setup
    original = schedule(sitting_setup).json()
    batch = {"registrations": [registration(candidates[0])]}
    registered = db.client.post(url + "/registrations", headers=staff, json=batch)
    assert registered.status_code == 200
    assert db.client.get(url + "/cancellation", headers=staff).status_code == 404
    response = cancel(sitting_setup)
    assert response.status_code == 200, response.text
    assert cancel(sitting_setup).json() == response.json()
    assert cancel(sitting_setup, {"reason_code": "operational"}).status_code == 409
    assert db.client.get(url + "/cancellation", headers=staff).json() == response.json()
    assert db.client.get(url, headers=staff).json() == original
    assert db.client.put(url, headers=staff, json=body).json() == original
    assert db.client.post(url + "/registrations", headers=staff, json=batch).json() == registered.json()
    assert (
        db.client.post(
            url + "/registrations", headers=staff, json={"registrations": [registration(candidates[1])]}
        ).status_code
        == 409
    )
    with db.admin_engine.begin() as c:
        context(c, db)
        assert c.scalar(text("SELECT count(*) FROM audit_records WHERE action='exam.sitting_cancelled'")) == 1
        assert (
            c.scalar(
                text("SELECT count(*) FROM outbox_events WHERE payload->>'action'='exam.sitting_cancelled'")
            )
            == 1
        )


def test_candidate_eligibility_and_sql_visibility(sitting_setup):
    db, staff, _, candidates, url, _ = sitting_setup
    schedule(sitting_setup)
    assert (
        db.client.post(
            url + "/registrations", headers=staff, json={"registrations": [registration(candidates[0])]}
        ).status_code
        == 200
    )
    assert cancel(sitting_setup).status_code == 200
    first, second = [db.login(candidate.hex) for candidate in candidates]
    response = db.client.get(url + "/eligibility", headers=first)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["window_state"] == "cancelled" and result["can_start"] is False
    assert result["deadline_if_started_now"] is None
    assert "reason_code" not in result and "cancelled_at" not in result
    assert db.client.get(url + "/eligibility", headers=second).status_code == 404
    assert db.client.put(url + "/cancellation", headers=first, json=BODY).status_code == 403
    assert db.client.get(url + "/cancellation", headers=first).status_code == 403
    for candidate, count in zip(candidates, (1, 0), strict=True):
        db.ids["registered"] = candidate
        with db.runtime_engine.begin() as c:
            context(c, db, "registered")
            assert c.scalar(text("SELECT count(*) FROM sitting_cancellations")) == count


@pytest.mark.parametrize("table", ["audit_records", "outbox_events", "outbox_deliveries"])
def test_cancel_failure_rolls_back_business_and_events(sitting_setup, table):
    db, staff, _, _, url, _ = sitting_setup
    schedule(sitting_setup)
    engine = db.client.app.state.database.engine

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith("INSERT INTO " + table):
            raise SQLAlchemyError("Injected cancellation failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = cancel(sitting_setup)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503, response.text
    assert db.client.get(url + "/cancellation", headers=staff).status_code == 404
    with db.admin_engine.begin() as c:
        context(c, db)
        assert c.scalar(text("SELECT count(*) FROM sitting_cancellations")) == 0
        assert c.scalar(text("SELECT count(*) FROM audit_records WHERE action='exam.sitting_cancelled'")) == 0
        assert (
            c.scalar(
                text("SELECT count(*) FROM outbox_events WHERE payload->>'action'='exam.sitting_cancelled'")
            )
            == 0
        )
    assert cancel(sitting_setup).status_code == 200


def test_concurrent_cancel_retries(sitting_setup):
    db, _, _, _, _, _ = sitting_setup
    schedule(sitting_setup)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: cancel(sitting_setup), range(2)))
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json() == results[1].json()
    with db.admin_engine.begin() as c:
        context(c, db)
        assert c.scalar(text("SELECT count(*) FROM audit_records WHERE action='exam.sitting_cancelled'")) == 1


def test_cancel_and_registration_serialize(sitting_setup):
    db, staff, _, candidates, url, _ = sitting_setup
    schedule(sitting_setup)
    with ThreadPoolExecutor(max_workers=2) as executor:
        cancelled = executor.submit(cancel, sitting_setup)
        registered = executor.submit(
            db.client.post,
            url + "/registrations",
            headers=staff,
            json={"registrations": [registration(candidates[0])]},
        )
        assert cancelled.result().status_code == 200
        response = registered.result()
    assert response.status_code in (200, 409), response.text
    eligibility = db.client.get(url + "/eligibility", headers=db.login(candidates[0].hex))
    assert eligibility.status_code == (200 if response.status_code == 200 else 404)
    if eligibility.status_code == 200:
        assert eligibility.json()["can_start"] is False


def test_role_tenant_missing_sitting(sitting_setup):
    db, staff, reviewer, _, url, _ = sitting_setup
    schedule(sitting_setup)
    assert db.client.put(url + "/cancellation", headers=reviewer, json=BODY).status_code == 403
    foreign = url.replace(str(db.ids["tenant_a"]), str(db.ids["tenant_b"]))
    assert db.client.put(foreign + "/cancellation", headers=staff, json=BODY).status_code == 404
    assert (
        db.client.put(
            url.rsplit("/", 1)[0] + f"/{uuid4()}/cancellation", headers=staff, json=BODY
        ).status_code
        == 404
    )
    with db.runtime_engine.begin() as c:
        context(c, db, "admin_b", tenant="b")
        assert c.scalar(text("SELECT count(*) FROM sitting_cancellations")) == 0


@pytest.mark.parametrize(
    "operation",
    ["UPDATE sitting_cancellations SET reason_code='operational'", "DELETE FROM sitting_cancellations"],
)
def test_cancellation_immutable_owner_sql(sitting_setup, operation):
    db, _, _, _, _, _ = sitting_setup
    schedule(sitting_setup)
    assert cancel(sitting_setup).status_code == 200
    with pytest.raises(DBAPIError):
        with db.admin_engine.begin() as c:
            c.execute(text(operation))


def test_cancelled_sitting_blocks_direct_registration(sitting_setup):
    db, _, _, candidates, url, _ = sitting_setup
    schedule(sitting_setup)
    assert cancel(sitting_setup).status_code == 200
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as c:
            context(c, db)
            c.execute(
                text(
                    "INSERT INTO sitting_registrations(tenant_id,id,sitting_id,candidate_user_id,extra_minutes,allowed_minutes,created_by) VALUES(:tenant,:id,:sitting,:candidate,0,30,:actor)"
                ),
                {
                    "tenant": db.ids["tenant_a"],
                    "id": uuid4(),
                    "sitting": UUID(url.rsplit("/", 1)[1]),
                    "candidate": candidates[0],
                    "actor": db.ids["admin_a"],
                },
            )


@pytest.mark.parametrize(
    "trigger,table",
    [
        ("sitting_cancellation_guard", "sitting_cancellations"),
        ("registration_cancellation_guard", "sitting_registrations"),
    ],
)
def test_readiness_requires_cancellation_guards(security_database, trigger, table):
    db = security_database
    with db.admin_engine.begin() as c:
        c.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["runtime_role"] == "unsafe"


def test_worker_cannot_read_cancellations(outbox_database):
    with pytest.raises(DBAPIError):
        with outbox_database.worker_database.engine.begin() as c:
            c.execute(text("SELECT * FROM sitting_cancellations"))


def move_opening_into_past(db):
    """Owner-only clock fixture; restore the immutable guard in the same transaction."""
    with db.admin_engine.begin() as c:
        c.execute(text("ALTER TABLE exam_sittings DISABLE TRIGGER exam_sitting_guard"))
        c.execute(
            text(
                "UPDATE exam_sittings SET opens_at=clock_timestamp()-interval '1 hour', closes_at=clock_timestamp()+interval '2 hours'"
            )
        )
        c.execute(text("ALTER TABLE exam_sittings ENABLE TRIGGER exam_sitting_guard"))


def test_opened_sitting_rejects_new_cancellation(sitting_setup):
    db, _, _, _, url, _ = sitting_setup
    schedule(sitting_setup)
    move_opening_into_past(db)
    assert cancel(sitting_setup).status_code == 409
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as c:
            context(c, db)
            c.execute(
                text(
                    "INSERT INTO sitting_cancellations(tenant_id,sitting_id,reason_code,created_by) VALUES(:tenant,:sitting,'operational',:actor)"
                ),
                {
                    "tenant": db.ids["tenant_a"],
                    "sitting": UUID(url.rsplit("/", 1)[1]),
                    "actor": db.ids["admin_a"],
                },
            )


def test_existing_cancellation_retry_after_opening(sitting_setup):
    db, _, _, _, _, _ = sitting_setup
    schedule(sitting_setup)
    original = cancel(sitting_setup)
    assert original.status_code == 200
    move_opening_into_past(db)
    assert cancel(sitting_setup).json() == original.json()


def test_downgrade_preserves_cancellations(sitting_setup, test_database):
    from alembic import command

    db, _, _, _, _, _ = sitting_setup
    schedule(sitting_setup)
    assert cancel(sitting_setup).status_code == 200
    _, engine, config, _ = test_database
    try:
        with pytest.raises(DBAPIError):
            with engine.begin() as c:
                config.attributes["connection"] = c
                command.downgrade(config, "0014_exam_sittings")
    finally:
        config.attributes.pop("connection", None)
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM sitting_cancellations")) == 1
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0015_sitting_cancellations"


@pytest.mark.parametrize("privilege", ["SELECT", "INSERT"])
def test_readiness_requires_cancellation_grants(security_database, privilege):
    import psycopg
    from psycopg import sql

    db = security_database
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as c:
        c.execute(
            sql.SQL("REVOKE {} ON sitting_cancellations FROM {}").format(
                sql.SQL(privilege), sql.Identifier(db.runtime_engine.url.username)
            )
        )
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["runtime_role"] == "missing_grants"


def test_candidate_cannot_insert_cancellation(sitting_setup):
    db, _, _, candidates, url, _ = sitting_setup
    schedule(sitting_setup)
    db.ids["registered"] = candidates[0]
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as c:
            context(c, db, "registered")
            c.execute(
                text(
                    "INSERT INTO sitting_cancellations(tenant_id,sitting_id,reason_code,created_by) VALUES(:tenant,:sitting,'operational',:actor)"
                ),
                {
                    "tenant": db.ids["tenant_a"],
                    "sitting": UUID(url.rsplit("/", 1)[1]),
                    "actor": candidates[0],
                },
            )


@pytest.mark.parametrize(
    "body", [{"reason_code": "other"}, {"reason_code": "administrative", "reason": "free text"}, {}]
)
def test_cancellation_body_rejects_unregistered_or_private_fields(sitting_setup, body):
    db, staff, _, _, url, _ = sitting_setup
    schedule(sitting_setup)
    assert db.client.put(url + "/cancellation", headers=staff, json=body).status_code == 422
    assert db.client.get(url + "/cancellation", headers=staff).status_code == 404


def test_worker_provisioning_rejects_cancellation_privileges(outbox_database):
    import psycopg
    from psycopg import sql

    from app.db.provisioning import grant_worker

    db = outbox_database
    role = db.worker_database.engine.url.username
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as c:
        c.execute(sql.SQL("GRANT SELECT ON sitting_cancellations TO {}").format(sql.Identifier(role)))
    with psycopg.connect(dsn) as c:
        with pytest.raises(ValueError, match="separate"):
            grant_worker(c, role)
