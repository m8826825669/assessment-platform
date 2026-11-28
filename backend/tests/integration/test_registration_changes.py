"""SCH-01/TEN-01/GOV-01 registration lifecycle, timing and reason privacy."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
import test_exam_sittings
from sqlalchemy import event, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from test_exam_sittings import registration, schedule
from test_question_review import context
from test_sitting_cancellations import move_opening_into_past

from app.db.models import Membership, RegistrationChange, RegistrationChangeReason

pytestmark = pytest.mark.integration
REASON = "Private synthetic decision record"


@pytest.fixture
def change_setup(security_database):
    setup = test_exam_sittings.sitting_setup.__wrapped__(security_database)
    db, staff, reviewer, candidates, url, body = setup
    schedule(setup)
    reg = registration(candidates[0], extra=10)
    response = db.client.post(url + "/registrations", headers=staff, json={"registrations": [reg]})
    assert response.status_code == 200, response.text
    return db, staff, reviewer, candidates, url, body, reg, url + "/registrations/" + reg["id"]


def decision(setup, *, action="amend_accommodation", extra=20, revision=1, identity=None, reason=REASON):
    db, staff, _, _, _, _, _, url = setup
    body = {"action": action, "expected_revision": revision, "reason": reason}
    if action == "amend_accommodation":
        body["extra_minutes"] = extra
    return db.client.put(url + "/changes/" + str(identity or uuid4()), headers=staff, json=body)


def counts(db):
    with db.admin_engine.begin() as c:
        context(c, db)
        return tuple(
            c.scalar(text("SELECT count(*) FROM " + table))
            for table in (
                "registration_changes",
                "registration_change_reasons",
                "audit_records",
                "outbox_events",
                "outbox_deliveries",
            )
        )


def test_amendment_history_effective_allowance_and_frozen_receipt(change_setup):
    db, staff, _, candidates, sitting, _, reg, url = change_setup
    original = db.client.get(sitting + "/registrations", headers=staff).json()
    assert db.client.get(url + "/status", headers=staff).json()["revision"] == 1
    identity = uuid4()
    first = decision(change_setup, identity=identity)
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 2 and first.json()["allowed_minutes"] == 50
    assert decision(change_setup, identity=identity).json() == first.json()
    assert decision(change_setup, identity=identity, reason="Other reason").status_code == 409
    assert decision(change_setup, extra=5, revision=1).status_code == 409
    removal = decision(change_setup, extra=0, revision=2)
    assert removal.status_code == 200 and removal.json()["allowed_minutes"] == 30
    assert decision(change_setup, identity=identity).json() == first.json()
    assert db.client.get(sitting + "/registrations", headers=staff).json() == original
    assert (
        db.client.post(sitting + "/registrations", headers=staff, json={"registrations": [reg]}).json()
        == original
    )
    state = db.client.get(url + "/status", headers=staff).json()
    assert state["revision"] == 3 and state["extra_minutes"] == 0 and state["status"] == "active"
    history = db.client.get(url + "/changes", headers=staff).json()
    assert [row["revision"] for row in history] == [2, 3]
    assert db.client.get(url + "/changes?offset=1&limit=1", headers=staff).json() == history[1:]
    projection = db.client.get(sitting + "/eligibility", headers=db.login(candidates[0].hex)).json()
    assert projection["allowed_minutes"] == 30 and REASON not in str(projection)
    with db.admin_engine.begin() as c:
        context(c, db)
        assert REASON not in str(
            c.execute(
                text(
                    "SELECT before_state, after_state FROM audit_records WHERE action LIKE 'exam.registration_%'"
                )
            ).all()
        )
        assert REASON not in str(
            c.execute(
                text("SELECT payload FROM outbox_events WHERE payload->>'action' LIKE 'exam.registration_%'")
            ).all()
        )


def test_withdrawal_is_terminal_without_deleting_registration(change_setup):
    db, staff, _, candidates, sitting, _, reg, url = change_setup
    identity = uuid4()
    withdrawn = decision(change_setup, action="withdraw", identity=identity)
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["extra_minutes"] == 10
    assert decision(change_setup, action="withdraw", identity=identity).json() == withdrawn.json()
    assert decision(change_setup, extra=30, revision=2).status_code == 409
    assert decision(change_setup, action="withdraw", revision=2).status_code == 409
    projection = db.client.get(sitting + "/eligibility", headers=db.login(candidates[0].hex)).json()
    assert projection["window_state"] == "withdrawn" and projection["can_start"] is False
    assert projection["deadline_if_started_now"] is None
    assert db.client.get(url + "/status", headers=staff).json()["status"] == "withdrawn"
    assert (
        db.client.post(sitting + "/registrations", headers=staff, json={"registrations": [reg]}).status_code
        == 200
    )
    assert (
        db.client.post(
            sitting + "/registrations", headers=staff, json={"registrations": [registration(candidates[0])]}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("action", ["withdraw", "amend_accommodation"])
@pytest.mark.parametrize(
    "table", ["registration_change_reasons", "audit_records", "outbox_events", "outbox_deliveries"]
)
def test_decision_failure_rolls_back_every_record(change_setup, action, table):
    db = change_setup[0]
    before = counts(db)
    engine = db.client.app.state.database.engine

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith("INSERT INTO " + table):
            raise SQLAlchemyError("Injected registration decision failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = decision(change_setup, action=action)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503, response.text
    assert counts(db) == before
    assert decision(change_setup, action=action).status_code == 200


@pytest.mark.parametrize("same_id", [True, False])
def test_concurrent_revision_decisions_are_fenced(change_setup, same_id):
    db, staff, _, _, _, _, _, url = change_setup
    first = uuid4()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda identity: decision(change_setup, identity=identity),
                [first, first if same_id else uuid4()],
            )
        )
    assert sorted(r.status_code for r in results) == ([200, 200] if same_id else [200, 409])
    assert len(db.client.get(url + "/changes", headers=staff).json()) == 1
    if same_id:
        assert results[0].json() == results[1].json()


def test_cancel_and_amendment_serialize(change_setup):
    db, staff, _, candidates, sitting, _, _, _ = change_setup
    with ThreadPoolExecutor(max_workers=2) as executor:
        amendment = executor.submit(decision, change_setup)
        cancellation = executor.submit(
            db.client.put, sitting + "/cancellation", headers=staff, json={"reason_code": "administrative"}
        )
        assert cancellation.result().status_code == 200
        assert amendment.result().status_code in (200, 409)
    assert (
        db.client.get(sitting + "/eligibility", headers=db.login(candidates[0].hex)).json()["window_state"]
        == "cancelled"
    )


def test_cutoff_replay_and_cancelled_sitting(change_setup):
    db, staff, _, _, sitting, _, _, _ = change_setup
    identity = uuid4()
    response = decision(change_setup, identity=identity)
    assert response.status_code == 200
    assert (
        db.client.put(
            sitting + "/cancellation", headers=staff, json={"reason_code": "operational"}
        ).status_code
        == 200
    )
    assert decision(change_setup, action="withdraw", revision=2).status_code == 409
    move_opening_into_past(db)
    assert decision(change_setup, identity=identity).json() == response.json()
    assert decision(change_setup, extra=30, revision=2).status_code == 409


def test_unchanged_and_oversized_allowances_rejected(change_setup):
    assert decision(change_setup, extra=10).status_code == 409
    assert decision(change_setup, extra=240).status_code == 409


def test_private_reason_sql_isolation_and_revocation(change_setup):
    db, staff, reviewer, candidates, sitting, _, _, url = change_setup
    assert decision(change_setup).status_code == 200
    first = db.login(candidates[0].hex)
    for suffix in ("/changes", "/status"):
        assert db.client.get(url + suffix, headers=first).status_code == 403
        assert db.client.get(url + suffix, headers=reviewer).status_code == 403
    for candidate, count in zip(candidates, (1, 0), strict=True):
        db.ids["registered"] = candidate
        with db.runtime_engine.begin() as c:
            context(c, db, "registered")
            assert c.scalar(text("SELECT count(*) FROM registration_changes")) == count
            assert c.scalar(text("SELECT count(*) FROM registration_change_reasons")) == 0
    with db.runtime_engine.begin() as c:
        context(c, db, "admin_b", tenant="b")
        assert c.scalar(text("SELECT count(*) FROM registration_changes")) == 0
        assert c.scalar(text("SELECT count(*) FROM registration_change_reasons")) == 0
    with db.admin_engine.begin() as c:
        context(c, db)
        c.execute(
            update(Membership)
            .where(Membership.tenant_id == db.ids["tenant_a"], Membership.user_id == candidates[0])
            .values(status="suspended")
        )
    assert db.client.get(sitting + "/eligibility", headers=first).status_code == 404
    assert decision(change_setup, extra=30, revision=2).status_code == 409
    assert decision(change_setup, action="withdraw", revision=2).status_code == 200
    db.ids["registered"] = candidates[0]
    with db.runtime_engine.begin() as c:
        context(c, db, "registered")
        assert c.scalar(text("SELECT count(*) FROM registration_changes")) == 0


@pytest.mark.parametrize("table", ["registration_changes", "registration_change_reasons"])
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_history_and_reasons_are_immutable_owner_sql(change_setup, table, operation):
    db = change_setup[0]
    assert decision(change_setup).status_code == 200
    statement = (
        "DELETE FROM " + table
        if operation == "delete"
        else (
            "UPDATE registration_changes SET extra_minutes=1"
            if table == "registration_changes"
            else "UPDATE registration_change_reasons SET reason='changed'"
        )
    )
    with pytest.raises(DBAPIError):
        with db.admin_engine.begin() as c:
            c.execute(text(statement))


def insert_decision(c, setup, **overrides):
    db, _, _, candidates, sitting, _, reg, _ = setup
    values = dict(
        tenant_id=db.ids["tenant_a"],
        id=uuid4(),
        registration_id=UUID(reg["id"]),
        sitting_id=UUID(sitting.rsplit("/", 1)[1]),
        candidate_user_id=candidates[0],
        revision=2,
        action="amend_accommodation",
        extra_minutes=20,
        allowed_minutes=50,
        created_by=db.ids["admin_a"],
    )
    values.update(overrides)
    c.execute(RegistrationChange.__table__.insert().values(**values))
    return values


@pytest.mark.parametrize(
    "kind",
    [
        "stale",
        "forged_candidate",
        "forged_sitting",
        "bad_allowance",
        "missing_reason",
        "candidate",
        "foreign_tenant",
    ],
)
def test_direct_sql_cannot_bypass_registration_decision_boundaries(change_setup, kind):
    db, _, _, candidates, _, _, _, _ = change_setup
    modifications = {
        "stale": {"revision": 3},
        "forged_candidate": {"candidate_user_id": candidates[1]},
        "forged_sitting": {"sitting_id": uuid4()},
        "bad_allowance": {"allowed_minutes": 999},
    }
    db.ids["registered"] = candidates[0]
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as c:
            context(
                c,
                db,
                "registered" if kind == "candidate" else "admin_b" if kind == "foreign_tenant" else "admin_a",
                tenant="b" if kind == "foreign_tenant" else "a",
            )
            values = insert_decision(c, change_setup, **modifications.get(kind, {}))
            if kind != "missing_reason":
                c.execute(
                    RegistrationChangeReason.__table__.insert().values(
                        tenant_id=values["tenant_id"], change_id=values["id"], reason=REASON
                    )
                )
    assert counts(db)[:2] == (0, 0)


@pytest.mark.parametrize(
    "trigger,table",
    [
        ("registration_change_guard", "registration_changes"),
        ("registration_change_reason_guard", "registration_change_reasons"),
        ("registration_change_reason_required", "registration_changes"),
    ],
)
def test_readiness_requires_registration_decision_guards(security_database, trigger, table):
    db = security_database
    with db.admin_engine.begin() as c:
        c.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["runtime_role"] == "unsafe"


@pytest.mark.parametrize("table", ["registration_changes", "registration_change_reasons"])
def test_worker_has_no_decision_privileges(outbox_database, table):
    with pytest.raises(DBAPIError):
        with outbox_database.worker_database.engine.begin() as c:
            c.execute(text("SELECT * FROM " + table))


def test_nonempty_downgrade_preserves_registration_decisions(change_setup, test_database):
    from alembic import command

    assert decision(change_setup).status_code == 200
    _, engine, config, _ = test_database
    try:
        with pytest.raises(DBAPIError):
            with engine.begin() as c:
                config.attributes["connection"] = c
                command.downgrade(config, "0015_sitting_cancellations")
    finally:
        config.attributes.pop("connection", None)
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM registration_changes")) == 1
        assert c.scalar(text("SELECT count(*) FROM registration_change_reasons")) == 1


@pytest.mark.parametrize("table", ["registration_changes", "registration_change_reasons"])
@pytest.mark.parametrize("privilege", ["SELECT", "INSERT"])
def test_readiness_requires_decision_privileges(security_database, table, privilege):
    import psycopg
    from psycopg import sql

    db = security_database
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as c:
        c.execute(
            sql.SQL("REVOKE {} ON {} FROM {}").format(
                sql.SQL(privilege), sql.Identifier(table), sql.Identifier(db.runtime_engine.url.username)
            )
        )
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["runtime_role"] == "missing_grants"


@pytest.mark.parametrize("table", ["registration_changes", "registration_change_reasons"])
def test_worker_provisioning_refuses_decision_privileges(outbox_database, table):
    import psycopg
    from psycopg import sql

    from app.db.provisioning import grant_worker

    db = outbox_database
    role = db.worker_database.engine.url.username
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as c:
        c.execute(sql.SQL("GRANT INSERT ON {} TO {}").format(sql.Identifier(table), sql.Identifier(role)))
    with psycopg.connect(dsn) as c:
        with pytest.raises(ValueError, match="separate"):
            grant_worker(c, role)


@pytest.mark.parametrize("lifecycle", ["opened", "withdrawn", "cancelled"])
def test_direct_sql_cannot_change_terminal_or_open_registration(change_setup, lifecycle):
    db, staff, _, _, sitting, _, _, _ = change_setup
    revision = 2
    if lifecycle == "opened":
        move_opening_into_past(db)
        assert decision(change_setup).status_code == 409
    elif lifecycle == "withdrawn":
        assert decision(change_setup, action="withdraw").status_code == 200
        revision = 3
    else:
        assert (
            db.client.put(
                sitting + "/cancellation", headers=staff, json={"reason_code": "administrative"}
            ).status_code
            == 200
        )
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as c:
            context(c, db)
            values = insert_decision(c, change_setup, revision=revision)
            c.execute(
                RegistrationChangeReason.__table__.insert().values(
                    tenant_id=values["tenant_id"], change_id=values["id"], reason=REASON
                )
            )


def test_retry_requires_current_staff_authority(change_setup):
    db, _, _, _, _, _, _, _ = change_setup
    identity = uuid4()
    assert decision(change_setup, identity=identity).status_code == 200
    with db.admin_engine.begin() as c:
        context(c, db)
        c.execute(
            update(Membership)
            .where(Membership.id == db.ids["membership_candidate"])
            .values(status="suspended")
        )
    assert decision(change_setup, identity=identity).status_code == 404


def test_change_route_role_tenant_and_registration_binding(change_setup):
    db, staff, reviewer, candidates, sitting, _, _, url = change_setup
    body = {"action": "withdraw", "expected_revision": 1, "reason": REASON}
    endpoint = url + "/changes/" + str(uuid4())
    assert db.client.put(endpoint, headers=reviewer, json=body).status_code == 403
    assert db.client.put(endpoint, headers=db.login(candidates[0].hex), json=body).status_code == 403
    assert (
        db.client.put(
            endpoint.replace(str(db.ids["tenant_a"]), str(db.ids["tenant_b"])), headers=staff, json=body
        ).status_code
        == 404
    )
    identity = uuid4()
    assert decision(change_setup, identity=identity).status_code == 200
    reg = registration(candidates[1])
    assert (
        db.client.post(sitting + "/registrations", headers=staff, json={"registrations": [reg]}).status_code
        == 200
    )
    other = sitting + "/registrations/" + reg["id"] + "/changes/" + str(identity)
    assert (
        db.client.put(
            other,
            headers=staff,
            json={
                "action": "amend_accommodation",
                "expected_revision": 1,
                "extra_minutes": 20,
                "reason": REASON,
            },
        ).status_code
        == 409
    )
