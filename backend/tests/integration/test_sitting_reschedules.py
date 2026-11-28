"""SCH-01/PUB-01/TEN-01/GOV-01 atomic unopened sitting replacement."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
import test_exam_sittings
from sqlalchemy import event, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from test_exam_sittings import registration
from test_question_review import context
from test_sitting_cancellations import move_opening_into_past

from app.db.database import EXPECTED_DATABASE_REVISION
from app.db.models import Membership, SittingReschedule

pytestmark = pytest.mark.integration


@pytest.fixture
def reschedule_setup(security_database):
    setup = test_exam_sittings.sitting_setup.__wrapped__(security_database)
    test_exam_sittings.schedule(setup)
    db, staff, reviewer, candidates, url, body = setup
    opening = datetime.fromisoformat(body["opens_at"]) + timedelta(days=1)
    change = {
        "replacement_id": str(uuid4()),
        "opens_at": opening.isoformat(),
        "closes_at": (opening + timedelta(hours=2)).isoformat(),
        "reason_code": "schedule_error",
    }
    return db, staff, reviewer, candidates, url, body, change


def replace(setup, body=None):
    db, staff, _, _, url, _, change = setup
    return db.client.post(url + "/reschedule", headers=staff, json=change if body is None else body)


def counts(db):
    with db.admin_engine.begin() as c:
        context(c, db)
        return tuple(
            c.scalar(text("SELECT count(*) FROM " + table))
            for table in (
                "exam_sittings",
                "sitting_cancellations",
                "sitting_reschedules",
                "sitting_registrations",
                "audit_records",
                "outbox_events",
                "outbox_deliveries",
            )
        )


def test_reschedule_is_atomic_preserves_snapshots_and_needs_explicit_registration(reschedule_setup):
    db, staff, _, candidates, url, body, change = reschedule_setup
    original = db.client.get(url, headers=staff).json()
    reg = registration(candidates[0], extra=15)
    assert (
        db.client.post(url + "/registrations", headers=staff, json={"registrations": [reg]}).status_code
        == 200
    )
    registered = db.client.get(url + "/registrations", headers=staff).json()
    candidate = db.login(candidates[0].hex)
    assert db.client.get(url + "/reschedule", headers=staff).status_code == 404
    response = replace(reschedule_setup)
    assert response.status_code == 200, response.text
    result = response.json()
    replacement_url = url.rsplit("/", 1)[0] + "/" + change["replacement_id"]
    saved = result["replacement"]
    assert result["sitting_id"] == original["id"]
    for key in ("title", "publication_id", "policy", "duration_minutes", "display_timezone"):
        assert saved[key] == original[key]
    assert db.client.get(url, headers=staff).json() == original
    assert db.client.get(url + "/registrations", headers=staff).json() == registered
    assert db.client.get(replacement_url + "/registrations", headers=staff).json() == []
    assert db.client.get(url + "/eligibility", headers=candidate).json()["window_state"] == "cancelled"
    assert db.client.get(replacement_url + "/eligibility", headers=candidate).status_code == 404
    assert db.client.get(url + "/reschedule", headers=staff).json() == result
    before = counts(db)
    assert replace(reschedule_setup).json() == result
    assert counts(db) == before
    fresh = registration(candidates[0], extra=10)
    assert (
        db.client.post(
            replacement_url + "/registrations", headers=staff, json={"registrations": [fresh]}
        ).status_code
        == 200
    )
    assert db.client.get(replacement_url + "/eligibility", headers=candidate).json()["allowed_minutes"] == 40
    with db.admin_engine.begin() as c:
        context(c, db)
        assert (
            c.scalar(text("SELECT count(*) FROM audit_records WHERE action='exam.sitting_rescheduled'")) == 1
        )
        assert c.scalar(text("SELECT count(*) FROM audit_records WHERE action='exam.sitting_cancelled'")) == 1


@pytest.mark.parametrize(
    "key,value", [("reason_code", "operational"), ("replacement_id", None), ("display_timezone", "UTC")]
)
def test_replay_conflicts_leave_every_record_unchanged(reschedule_setup, key, value):
    db, _, _, _, _, _, body = reschedule_setup
    assert replace(reschedule_setup).status_code == 200
    before = counts(db)
    changed = {**body, key: str(uuid4()) if value is None else value}
    assert replace(reschedule_setup, changed).status_code == 409
    assert counts(db) == before


@pytest.mark.parametrize("table", ["audit_records", "outbox_events", "outbox_deliveries"])
@pytest.mark.parametrize("stage", [1, 2, 3])
def test_every_reschedule_stage_rolls_back_on_event_failure(reschedule_setup, table, stage):
    db = reschedule_setup[0]
    before = counts(db)
    engine = db.client.app.state.database.engine
    seen = 0

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        nonlocal seen
        if statement.startswith("INSERT INTO " + table):
            seen += 1
            if seen == stage:
                raise SQLAlchemyError("Injected reschedule transaction failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = replace(reschedule_setup)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503, response.text
    assert counts(db) == before
    assert replace(reschedule_setup).status_code == 200


@pytest.mark.parametrize("same_id", [True, False])
def test_concurrent_replacement_requests_have_one_winner_or_receipt(reschedule_setup, same_id):
    db, _, _, _, _, _, body = reschedule_setup
    other = body if same_id else {**body, "replacement_id": str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda payload: replace(reschedule_setup, payload), [body, other]))
    assert sorted(r.status_code for r in results) == ([200, 200] if same_id else [200, 409])
    assert counts(db)[:3] == (2, 1, 1)
    if same_id:
        assert results[0].json() == results[1].json()


def test_cancellation_and_reschedule_serialize(reschedule_setup):
    db, staff, _, _, url, _, _ = reschedule_setup
    with ThreadPoolExecutor(max_workers=2) as executor:
        change = executor.submit(replace, reschedule_setup)
        cancelled = executor.submit(
            db.client.put, url + "/cancellation", headers=staff, json={"reason_code": "operational"}
        )
        left, right = change.result(), cancelled.result()
    assert sorted([left.status_code, right.status_code]) == [200, 409]
    state = counts(db)
    assert state[:3] == ((2, 1, 1) if left.status_code == 200 else (1, 1, 0))


def test_existing_or_same_target_and_short_or_past_window_are_rejected(reschedule_setup):
    db, _, _, _, url, body, change = reschedule_setup
    before = counts(db)
    assert replace(reschedule_setup, {**change, "replacement_id": url.rsplit("/", 1)[1]}).status_code == 409
    short = (datetime.fromisoformat(change["opens_at"]) + timedelta(minutes=1)).isoformat()
    assert replace(reschedule_setup, {**change, "closes_at": short}).status_code == 422
    assert replace(reschedule_setup, {**change, "opens_at": "2020-01-01T00:00:00Z"}).status_code == 409
    assert counts(db) == before


def test_old_open_or_cancelled_sitting_cannot_be_replaced(reschedule_setup):
    db, staff, _, _, url, _, _ = reschedule_setup
    assert (
        db.client.put(
            url + "/cancellation", headers=staff, json={"reason_code": "schedule_error"}
        ).status_code
        == 200
    )
    assert replace(reschedule_setup).status_code == 409
    move_opening_into_past(db)
    assert replace(reschedule_setup).status_code == 409
    assert counts(db)[:3] == (1, 1, 0)


def test_historical_retry_survives_later_reschedule_and_opening(reschedule_setup):
    db, staff, _, _, url, _, change = reschedule_setup
    original = replace(reschedule_setup)
    assert original.status_code == 200
    replacement = url.rsplit("/", 1)[0] + "/" + change["replacement_id"]
    next_body = {**change, "replacement_id": str(uuid4()), "display_timezone": "UTC"}
    next_result = db.client.post(replacement + "/reschedule", headers=staff, json=next_body)
    assert next_result.status_code == 200, next_result.text
    assert replace(reschedule_setup).json() == original.json()
    # Advance only the original cutoff; keep the replacement's immutable request snapshot intact.
    with db.admin_engine.begin() as c:
        c.execute(text("ALTER TABLE exam_sittings DISABLE TRIGGER exam_sitting_guard"))
        c.execute(
            text(
                "UPDATE exam_sittings SET opens_at=clock_timestamp()-interval '1 hour', closes_at=clock_timestamp()+interval '2 hours' WHERE id=:original"
            ),
            {"original": UUID(url.rsplit("/", 1)[1])},
        )
        c.execute(text("ALTER TABLE exam_sittings ENABLE TRIGGER exam_sitting_guard"))
    assert replace(reschedule_setup).json() == original.json()


def test_role_tenant_and_candidate_sql_boundaries(reschedule_setup):
    db, staff, reviewer, candidates, url, _, body = reschedule_setup
    assert db.client.post(url + "/reschedule", headers=reviewer, json=body).status_code == 403
    candidate = db.login(candidates[0].hex)
    assert db.client.post(url + "/reschedule", headers=candidate, json=body).status_code == 403
    foreign = url.replace(str(db.ids["tenant_a"]), str(db.ids["tenant_b"]))
    assert db.client.post(foreign + "/reschedule", headers=staff, json=body).status_code == 404
    assert replace(reschedule_setup).status_code == 200
    assert db.client.get(url + "/reschedule", headers=candidate).status_code == 403
    db.ids["registered"] = candidates[0]
    for actor, tenant in [("registered", "a"), ("admin_b", "b")]:
        with db.runtime_engine.begin() as c:
            context(c, db, actor, tenant=tenant)
            assert c.scalar(text("SELECT count(*) FROM sitting_reschedules")) == 0


@pytest.mark.parametrize(
    "operation",
    ["UPDATE sitting_reschedules SET reason_code='operational'", "DELETE FROM sitting_reschedules"],
)
def test_reschedule_links_are_immutable_even_for_owner(reschedule_setup, operation):
    db = reschedule_setup[0]
    assert replace(reschedule_setup).status_code == 200
    with pytest.raises(DBAPIError):
        with db.admin_engine.begin() as c:
            c.execute(text(operation))


def test_sql_rejects_link_without_matching_cancelled_source(reschedule_setup):
    db, staff, _, _, url, body, change = reschedule_setup
    target_url = url.rsplit("/", 1)[0] + "/" + change["replacement_id"]
    assert (
        db.client.put(
            target_url,
            headers=staff,
            json={**body, "opens_at": change["opens_at"], "closes_at": change["closes_at"]},
        ).status_code
        == 200
    )
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as c:
            context(c, db, "candidate")
            c.execute(
                SittingReschedule.__table__.insert().values(
                    tenant_id=db.ids["tenant_a"],
                    sitting_id=UUID(url.rsplit("/", 1)[1]),
                    replacement_id=UUID(change["replacement_id"]),
                    reason_code="schedule_error",
                    created_by=db.ids["candidate"],
                )
            )
    assert counts(db)[2] == 0


def test_runtime_readiness_requires_reschedule_guard(security_database):
    db = security_database
    with db.admin_engine.begin() as c:
        c.execute(text("ALTER TABLE sitting_reschedules DISABLE TRIGGER sitting_reschedule_guard"))
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["runtime_role"] == "unsafe"


@pytest.mark.parametrize("privilege", ["SELECT", "INSERT"])
def test_readiness_requires_reschedule_grants(security_database, privilege):
    import psycopg
    from psycopg import sql

    db = security_database
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as c:
        c.execute(
            sql.SQL("REVOKE {} ON sitting_reschedules FROM {}").format(
                sql.SQL(privilege), sql.Identifier(db.runtime_engine.url.username)
            )
        )
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["runtime_role"] == "missing_grants"


def test_worker_cannot_read_reschedule_history(outbox_database):
    with pytest.raises(DBAPIError):
        with outbox_database.worker_database.engine.begin() as c:
            c.execute(text("SELECT * FROM sitting_reschedules"))


def test_worker_provisioning_refuses_reschedule_privileges(outbox_database):
    import psycopg
    from psycopg import sql

    from app.db.provisioning import grant_worker

    db = outbox_database
    role = db.worker_database.engine.url.username
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as c:
        c.execute(sql.SQL("GRANT SELECT ON sitting_reschedules TO {}").format(sql.Identifier(role)))
    with psycopg.connect(dsn) as c:
        with pytest.raises(ValueError, match="separate"):
            grant_worker(c, role)


def test_downgrade_refuses_to_discard_reschedule_history(reschedule_setup, test_database):
    from alembic import command

    assert replace(reschedule_setup).status_code == 200
    _, engine, config, _ = test_database
    try:
        with pytest.raises(DBAPIError):
            with engine.begin() as c:
                config.attributes["connection"] = c
                command.downgrade(config, "0016_registration_changes")
    finally:
        config.attributes.pop("connection", None)
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM sitting_reschedules")) == 1
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_DATABASE_REVISION


def test_replay_rechecks_current_staff_authority(reschedule_setup):
    db = reschedule_setup[0]
    assert replace(reschedule_setup).status_code == 200
    with db.admin_engine.begin() as c:
        context(c, db)
        c.execute(
            update(Membership)
            .where(Membership.id == db.ids["membership_candidate"])
            .values(status="suspended")
        )
    assert replace(reschedule_setup).status_code == 404


@pytest.mark.parametrize("kind", ["changed_title", "registered_target", "cancelled_target", "other_actor"])
def test_sql_rejects_incoherent_or_nonempty_replacement(reschedule_setup, kind):
    db, staff, _, candidates, url, body, change = reschedule_setup
    target = url.rsplit("/", 1)[0] + "/" + change["replacement_id"]
    payload = {**body, "opens_at": change["opens_at"], "closes_at": change["closes_at"]}
    if kind == "changed_title":
        payload["title"] = "Different sitting purpose"
    assert db.client.put(target, headers=staff, json=payload).status_code == 200
    if kind == "registered_target":
        assert (
            db.client.post(
                target + "/registrations",
                headers=staff,
                json={"registrations": [registration(candidates[0])]},
            ).status_code
            == 200
        )
    elif kind == "cancelled_target":
        assert (
            db.client.put(
                target + "/cancellation", headers=staff, json={"reason_code": "schedule_error"}
            ).status_code
            == 200
        )
    assert (
        db.client.put(
            url + "/cancellation", headers=staff, json={"reason_code": "schedule_error"}
        ).status_code
        == 200
    )
    actor = "admin_a" if kind == "other_actor" else "candidate"
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as c:
            context(c, db, actor)
            c.execute(
                SittingReschedule.__table__.insert().values(
                    tenant_id=db.ids["tenant_a"],
                    sitting_id=UUID(url.rsplit("/", 1)[1]),
                    replacement_id=UUID(change["replacement_id"]),
                    reason_code="schedule_error",
                    created_by=db.ids[actor],
                )
            )
    assert counts(db)[2] == 0


def test_reschedule_does_not_reuse_an_existing_identical_target(reschedule_setup):
    db, staff, _, _, url, body, change = reschedule_setup
    target = url.rsplit("/", 1)[0] + "/" + change["replacement_id"]
    assert (
        db.client.put(
            target,
            headers=staff,
            json={**body, "opens_at": change["opens_at"], "closes_at": change["closes_at"]},
        ).status_code
        == 200
    )
    before = counts(db)
    assert replace(reschedule_setup).status_code == 409
    assert counts(db) == before


def test_reschedule_and_original_registration_serialize(reschedule_setup):
    db, staff, _, candidates, url, _, body = reschedule_setup
    with ThreadPoolExecutor(max_workers=2) as executor:
        changing = executor.submit(replace, reschedule_setup)
        registering = executor.submit(
            db.client.post,
            url + "/registrations",
            headers=staff,
            json={"registrations": [registration(candidates[0])]},
        )
        assert changing.result().status_code == 200
        response = registering.result()
    assert response.status_code in (200, 409)
    target = url.rsplit("/", 1)[0] + "/" + body["replacement_id"]
    assert db.client.get(target + "/registrations", headers=staff).json() == []
    candidate = db.login(candidates[0].hex)
    original = db.client.get(url + "/eligibility", headers=candidate)
    assert original.status_code == (200 if response.status_code == 200 else 404)
    if original.status_code == 200:
        assert original.json()["can_start"] is False


def test_uncancelled_open_source_is_denied(reschedule_setup):
    db = reschedule_setup[0]
    move_opening_into_past(db)
    before = counts(db)
    assert replace(reschedule_setup).status_code == 409
    assert counts(db) == before
