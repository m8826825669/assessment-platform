"""SCH-01/TEN-01/GOV-01 candidate-owned invitation discovery and acknowledgement."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import test_exam_sittings
from sqlalchemy import event, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from test_exam_sittings import registration
from test_question_review import context, path

from app.db.database import EXPECTED_DATABASE_REVISION
from app.db.models import Membership, RegistrationAcceptance

pytestmark = pytest.mark.integration


@pytest.fixture
def invitation_setup(security_database):
    setup = test_exam_sittings.sitting_setup.__wrapped__(security_database)
    test_exam_sittings.schedule(setup)
    db, staff, reviewer, candidates, sitting, body = setup
    rows = [registration(candidates[0], extra=10), registration(candidates[1])]
    response = db.client.post(sitting + "/registrations", headers=staff, json={"registrations": rows})
    assert response.status_code == 200, response.text
    headers = [db.login(candidate.hex) for candidate in candidates]
    inbox = path(db, "exam-invitations")
    return db, staff, reviewer, candidates, sitting, body, rows, headers, inbox


def accept(setup, index=0):
    db, _, _, _, _, _, rows, headers, inbox = setup
    return db.client.post(inbox + "/" + rows[index]["id"] + "/accept", headers=headers[index])


def counts(db):
    with db.admin_engine.begin() as c:
        context(c, db)
        return tuple(
            c.scalar(text("SELECT count(*) FROM " + table))
            for table in (
                "registration_acceptances",
                "sitting_registrations",
                "registration_changes",
                "audit_records",
                "outbox_events",
                "outbox_deliveries",
            )
        )


def test_candidate_inbox_detail_acceptance_and_staff_receipt(invitation_setup):
    db, staff, _, _, sitting, _, rows, headers, inbox = invitation_setup
    before = counts(db)
    response = db.client.get(inbox, headers=headers[0])
    assert response.status_code == 200, response.text
    listing = response.json()
    assert listing["has_more"] is False and len(listing["items"]) == 1
    row = listing["items"][0]
    assert row["registration_id"] == rows[0]["id"] and row["allowed_minutes"] == 40
    assert row["can_accept"] is True and row["acceptance"] is None and row["can_start"] is False
    assert "Approved extra time" not in response.text and "policy" not in row and "content" not in row
    detail = db.client.get(inbox + "/" + rows[0]["id"], headers=headers[0])
    assert detail.status_code == 200 and detail.json()["registration_id"] == rows[0]["id"]
    assert counts(db) == before
    receipt = accept(invitation_setup)
    assert receipt.status_code == 200, receipt.text
    assert set(receipt.json()) == {"registration_id", "sitting_id", "registration_revision", "accepted_at"}
    assert receipt.json()["registration_revision"] == 1
    saved = counts(db)
    assert accept(invitation_setup).json() == receipt.json() and counts(db) == saved
    staff_url = sitting + "/registrations/" + rows[0]["id"] + "/acceptance"
    assert db.client.get(staff_url, headers=staff).json() == receipt.json()
    assert db.client.get(staff_url, headers=headers[0]).status_code == 403
    updated = db.client.get(inbox, headers=headers[0]).json()["items"][0]
    assert updated["acceptance"] == receipt.json() and updated["can_accept"] is False
    assert updated["can_start"] is False
    with db.admin_engine.begin() as c:
        context(c, db)
        assert (
            c.scalar(text("SELECT count(*) FROM audit_records WHERE action='exam.invitation_accepted'")) == 1
        )


def test_inbox_filters_before_pagination_and_uses_deterministic_order(invitation_setup):
    db, staff, _, candidates, sitting, body, rows, headers, inbox = invitation_setup
    for day in (3, 2):
        new_id = uuid4()
        new_url = sitting.rsplit("/", 1)[0] + "/" + str(new_id)
        opening = datetime.fromisoformat(body["opens_at"]) + timedelta(days=day)
        assert (
            db.client.put(
                new_url,
                headers=staff,
                json={
                    **body,
                    "opens_at": opening.isoformat(),
                    "closes_at": (opening + timedelta(hours=2)).isoformat(),
                },
            ).status_code
            == 200
        )
        assert (
            db.client.post(
                new_url + "/registrations",
                headers=staff,
                json={"registrations": [registration(candidates[0])]},
            ).status_code
            == 200
        )
    first = db.client.get(inbox + "?limit=1", headers=headers[0]).json()
    second = db.client.get(inbox + "?offset=1&limit=1", headers=headers[0]).json()
    third = db.client.get(inbox + "?offset=2&limit=1", headers=headers[0]).json()
    assert first["has_more"] is True and second["has_more"] is True and third["has_more"] is False
    assert first["items"][0]["registration_id"] == rows[0]["id"]
    assert second["items"][0]["opens_at"] < third["items"][0]["opens_at"]
    assert db.client.get(inbox + "?offset=3&limit=1", headers=headers[0]).json()["items"] == []
    assert len(db.client.get(inbox, headers=headers[1]).json()["items"]) == 1


def test_acceptance_and_current_allowance_are_distinct_after_amendment(invitation_setup):
    db, staff, _, _, sitting, _, rows, headers, inbox = invitation_setup
    receipt = accept(invitation_setup)
    assert receipt.status_code == 200
    changed = db.client.put(
        sitting + "/registrations/" + rows[0]["id"] + "/changes/" + str(uuid4()),
        headers=staff,
        json={
            "expected_revision": 1,
            "action": "amend_accommodation",
            "extra_minutes": 20,
            "reason": "Private synthetic accommodation review",
        },
    )
    assert changed.status_code == 200
    listed = db.client.get(inbox, headers=headers[0]).json()["items"][0]
    detail = db.client.get(inbox + "/" + rows[0]["id"], headers=headers[0]).json()
    assert listed["allowed_minutes"] == detail["allowed_minutes"] == 50
    assert listed["registration_revision"] == 2 and listed["acceptance"]["registration_revision"] == 1
    assert "Private synthetic" not in str(listed)
    assert accept(invitation_setup).json() == receipt.json()
    assert db.client.get(sitting + "/eligibility", headers=headers[0]).json()["allowed_minutes"] == 50


@pytest.mark.parametrize("table", ["audit_records", "outbox_events", "outbox_deliveries"])
def test_acceptance_failure_rolls_back_receipt_and_events(invitation_setup, table):
    db = invitation_setup[0]
    before = counts(db)
    engine = db.client.app.state.database.engine

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith("INSERT INTO " + table):
            raise SQLAlchemyError("Injected acknowledgement failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = accept(invitation_setup)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503, response.text
    assert counts(db) == before
    assert accept(invitation_setup).status_code == 200


def test_concurrent_acceptance_retries_create_one_receipt(invitation_setup):
    db = invitation_setup[0]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: accept(invitation_setup), range(2)))
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json() == results[1].json()
    with db.admin_engine.begin() as c:
        context(c, db)
        assert c.scalar(text("SELECT count(*) FROM registration_acceptances")) == 1
        assert (
            c.scalar(
                text("SELECT count(*) FROM outbox_events WHERE payload->>'action'='exam.invitation_accepted'")
            )
            == 1
        )


def close_sitting(db, sitting):
    with db.admin_engine.begin() as c:
        c.execute(text("ALTER TABLE exam_sittings DISABLE TRIGGER exam_sitting_guard"))
        c.execute(
            text(
                "UPDATE exam_sittings SET opens_at=clock_timestamp()-interval '2 hours',closes_at=clock_timestamp()-interval '1 hour' WHERE id=:id"
            ),
            {"id": UUID(sitting.rsplit("/", 1)[1])},
        )
        c.execute(text("ALTER TABLE exam_sittings ENABLE TRIGGER exam_sitting_guard"))


@pytest.mark.parametrize("state", ["withdrawn", "cancelled", "closed"])
def test_new_acceptance_denied_but_receipt_replay_does_not_restore_eligibility(invitation_setup, state):
    db, staff, _, _, sitting, _, rows, headers, inbox = invitation_setup
    receipt = accept(invitation_setup, index=0)
    assert receipt.status_code == 200
    if state == "withdrawn":
        for row in rows:
            assert (
                db.client.put(
                    sitting + "/registrations/" + row["id"] + "/changes/" + str(uuid4()),
                    headers=staff,
                    json={"expected_revision": 1, "action": "withdraw", "reason": "Synthetic withdrawal"},
                ).status_code
                == 200
            )
    elif state == "cancelled":
        assert (
            db.client.put(
                sitting + "/cancellation", headers=staff, json={"reason_code": "administrative"}
            ).status_code
            == 200
        )
    else:
        close_sitting(db, sitting)
    assert accept(invitation_setup, index=1).status_code == 409
    before = counts(db)
    assert accept(invitation_setup, index=0).json() == receipt.json() and counts(db) == before
    item = db.client.get(inbox, headers=headers[0]).json()["items"][0]
    assert item["window_state"] == state and item["can_start"] is False and item["can_accept"] is False


def test_acceptance_is_allowed_after_opening_without_starting_attempt(invitation_setup):
    db, _, _, _, sitting, _, _, headers, inbox = invitation_setup
    with db.admin_engine.begin() as c:
        c.execute(text("ALTER TABLE exam_sittings DISABLE TRIGGER exam_sitting_guard"))
        c.execute(
            text(
                "UPDATE exam_sittings SET opens_at=clock_timestamp()-interval '1 hour',closes_at=clock_timestamp()+interval '1 hour'"
            )
        )
        c.execute(text("ALTER TABLE exam_sittings ENABLE TRIGGER exam_sitting_guard"))
    before = db.client.get(sitting + "/eligibility", headers=headers[0]).json()
    assert before["can_start"] is True
    assert accept(invitation_setup).status_code == 200
    after = db.client.get(inbox, headers=headers[0]).json()["items"][0]
    assert after["window_state"] == "open" and after["can_accept"] is False and after["can_start"] is True
    assert after["allowed_minutes"] == before["allowed_minutes"]


def test_candidate_ownership_tenant_roles_and_body_are_enforced(invitation_setup):
    db, staff, reviewer, _, _, _, rows, headers, inbox = invitation_setup
    assert db.client.get(inbox, headers=staff).status_code == 403
    assert db.client.get(inbox, headers=reviewer).status_code == 403
    assert db.client.get(inbox + "/" + rows[1]["id"], headers=headers[0]).status_code == 404
    assert db.client.post(inbox + "/" + rows[1]["id"] + "/accept", headers=headers[0]).status_code == 404
    assert db.client.post(inbox + "/" + rows[0]["id"] + "/accept", headers=staff).status_code == 403
    assert (
        db.client.post(
            inbox + "/" + rows[0]["id"] + "/accept", headers=headers[0], json={"registration_revision": 100}
        ).status_code
        == 422
    )
    assert (
        db.client.get(
            inbox.replace(str(db.ids["tenant_a"]), str(db.ids["tenant_b"])), headers=headers[0]
        ).status_code
        == 404
    )
    assert counts(db)[0] == 0


def test_revocation_hides_inbox_and_prevents_acceptance_replay(invitation_setup):
    db, _, _, candidates, _, _, rows, headers, inbox = invitation_setup
    assert accept(invitation_setup).status_code == 200
    with db.admin_engine.begin() as c:
        context(c, db)
        c.execute(
            update(Membership)
            .where(Membership.tenant_id == db.ids["tenant_a"], Membership.user_id == candidates[0])
            .values(status="suspended")
        )
    assert db.client.get(inbox, headers=headers[0]).status_code == 404
    assert accept(invitation_setup).status_code == 404
    db.ids["registered"] = candidates[0]
    with db.runtime_engine.begin() as c:
        context(c, db, "registered")
        assert c.scalar(text("SELECT count(*) FROM registration_acceptances")) == 0


def test_acceptance_sql_reads_are_own_only_and_staff_visible(invitation_setup):
    db, _, _, candidates, _, _, _, _, _ = invitation_setup
    assert accept(invitation_setup, index=0).status_code == 200
    assert accept(invitation_setup, index=1).status_code == 200
    for candidate in candidates:
        db.ids["registered"] = candidate
        with db.runtime_engine.begin() as c:
            context(c, db, "registered")
            assert c.scalars(text("SELECT candidate_user_id FROM registration_acceptances")).all() == [
                candidate
            ]
    with db.runtime_engine.begin() as c:
        context(c, db)
        assert c.scalar(text("SELECT count(*) FROM registration_acceptances")) == 2
    with db.runtime_engine.begin() as c:
        context(c, db, "admin_b", tenant="b")
        assert c.scalar(text("SELECT count(*) FROM registration_acceptances")) == 0


@pytest.mark.parametrize(
    "operation",
    ["DELETE FROM registration_acceptances", "UPDATE registration_acceptances SET registration_revision=2"],
)
def test_acceptance_receipts_are_immutable_owner_sql(invitation_setup, operation):
    db = invitation_setup[0]
    assert accept(invitation_setup).status_code == 200
    with pytest.raises(DBAPIError):
        with db.admin_engine.begin() as c:
            c.execute(text(operation))


@pytest.mark.parametrize(
    "kind", ["wrong_candidate", "wrong_sitting", "stale_revision", "staff_actor", "foreign_tenant"]
)
def test_direct_sql_cannot_forge_acceptance_binding(invitation_setup, kind):
    db, _, _, candidates, sitting, _, rows, _, _ = invitation_setup
    db.ids["registered"] = candidates[0]
    values = dict(
        tenant_id=db.ids["tenant_a"],
        registration_id=UUID(rows[0]["id"]),
        sitting_id=UUID(sitting.rsplit("/", 1)[1]),
        candidate_user_id=candidates[0],
        registration_revision=1,
    )
    if kind == "wrong_candidate":
        values["candidate_user_id"] = candidates[1]
    if kind == "wrong_sitting":
        values["sitting_id"] = uuid4()
    if kind == "stale_revision":
        values["registration_revision"] = 2
    actor = "admin_a" if kind == "staff_actor" else "admin_b" if kind == "foreign_tenant" else "registered"
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as c:
            context(c, db, actor, tenant="b" if kind == "foreign_tenant" else "a")
            c.execute(RegistrationAcceptance.__table__.insert().values(**values))
    assert counts(db)[0] == 0


def test_acceptance_and_withdrawal_serialize(invitation_setup):
    db, staff, _, _, sitting, _, rows, headers, inbox = invitation_setup
    with ThreadPoolExecutor(max_workers=2) as executor:
        acknowledging = executor.submit(accept, invitation_setup)
        withdrawing = executor.submit(
            db.client.put,
            sitting + "/registrations/" + rows[0]["id"] + "/changes/" + str(uuid4()),
            headers=staff,
            json={"expected_revision": 1, "action": "withdraw", "reason": "Synthetic withdrawal"},
        )
        assert withdrawing.result().status_code == 200
        assert acknowledging.result().status_code in (200, 409)
    item = db.client.get(inbox, headers=headers[0]).json()["items"][0]
    assert item["registration_status"] == "withdrawn" and item["can_start"] is False


def test_readiness_requires_acceptance_guard(security_database):
    db = security_database
    with db.admin_engine.begin() as c:
        c.execute(text("ALTER TABLE registration_acceptances DISABLE TRIGGER registration_acceptance_guard"))
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["runtime_role"] == "unsafe"


@pytest.mark.parametrize("privilege", ["SELECT", "INSERT"])
def test_readiness_requires_acceptance_grants(security_database, privilege):
    import psycopg
    from psycopg import sql

    db = security_database
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as c:
        c.execute(
            sql.SQL("REVOKE {} ON registration_acceptances FROM {}").format(
                sql.SQL(privilege), sql.Identifier(db.runtime_engine.url.username)
            )
        )
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["dependencies"]["runtime_role"] == "missing_grants"


def test_worker_has_no_acceptance_access(outbox_database):
    with pytest.raises(DBAPIError):
        with outbox_database.worker_database.engine.begin() as c:
            c.execute(text("SELECT * FROM registration_acceptances"))


def test_nonempty_downgrade_preserves_acceptance(invitation_setup, test_database):
    from alembic import command

    assert accept(invitation_setup).status_code == 200
    _, engine, config, _ = test_database
    try:
        with pytest.raises(DBAPIError):
            with engine.begin() as c:
                config.attributes["connection"] = c
                command.downgrade(config, "0017_sitting_reschedules")
    finally:
        config.attributes.pop("connection", None)
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM registration_acceptances")) == 1
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_DATABASE_REVISION


@pytest.mark.parametrize("state", ["withdrawn", "cancelled", "closed"])
def test_sql_cannot_accept_unavailable_invitation(invitation_setup, state):
    db, staff, _, candidates, sitting, _, rows, _, _ = invitation_setup
    if state == "withdrawn":
        assert (
            db.client.put(
                sitting + "/registrations/" + rows[0]["id"] + "/changes/" + str(uuid4()),
                headers=staff,
                json={"expected_revision": 1, "action": "withdraw", "reason": "Synthetic withdrawal"},
            ).status_code
            == 200
        )
    elif state == "cancelled":
        assert (
            db.client.put(
                sitting + "/cancellation", headers=staff, json={"reason_code": "operational"}
            ).status_code
            == 200
        )
    else:
        close_sitting(db, sitting)
    db.ids["registered"] = candidates[0]
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as c:
            context(c, db, "registered")
            c.execute(
                RegistrationAcceptance.__table__.insert().values(
                    tenant_id=db.ids["tenant_a"],
                    registration_id=UUID(rows[0]["id"]),
                    sitting_id=UUID(sitting.rsplit("/", 1)[1]),
                    candidate_user_id=candidates[0],
                    registration_revision=2 if state == "withdrawn" else 1,
                )
            )
    assert counts(db)[0] == 0


def test_sql_guard_owns_acceptance_timestamp(invitation_setup):
    db, _, _, candidates, sitting, _, rows, _, _ = invitation_setup
    db.ids["registered"] = candidates[0]
    before = datetime.now(UTC)
    with db.runtime_engine.begin() as c:
        context(c, db, "registered")
        stamp = c.scalar(
            RegistrationAcceptance.__table__.insert()
            .values(
                tenant_id=db.ids["tenant_a"],
                registration_id=UUID(rows[0]["id"]),
                sitting_id=UUID(sitting.rsplit("/", 1)[1]),
                candidate_user_id=candidates[0],
                registration_revision=1,
                accepted_at=datetime(2000, 1, 1, tzinfo=UTC),
            )
            .returning(RegistrationAcceptance.accepted_at)
        )
    assert before <= stamp <= datetime.now(UTC)


def test_worker_provisioning_refuses_acceptance_privileges(outbox_database):
    import psycopg
    from psycopg import sql

    from app.db.provisioning import grant_worker

    db = outbox_database
    role = db.worker_database.engine.url.username
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as c:
        c.execute(sql.SQL("GRANT INSERT ON registration_acceptances TO {}").format(sql.Identifier(role)))
    with psycopg.connect(dsn) as c:
        with pytest.raises(ValueError, match="separate"):
            grant_worker(c, role)


def test_rescheduling_does_not_transfer_invitation_acceptance(invitation_setup):
    db, staff, _, _, sitting, body, rows, headers, inbox = invitation_setup
    receipt = accept(invitation_setup)
    assert receipt.status_code == 200
    opening = datetime.fromisoformat(body["opens_at"]) + timedelta(days=1)
    replacement = str(uuid4())
    response = db.client.post(
        sitting + "/reschedule",
        headers=staff,
        json={
            "replacement_id": replacement,
            "opens_at": opening.isoformat(),
            "closes_at": (opening + timedelta(hours=2)).isoformat(),
            "reason_code": "schedule_error",
        },
    )
    assert response.status_code == 200, response.text
    items = db.client.get(inbox, headers=headers[0]).json()["items"]
    assert len(items) == 1 and items[0]["window_state"] == "cancelled"
    assert items[0]["acceptance"] == receipt.json()
    assert accept(invitation_setup).json() == receipt.json()
    assert (
        db.client.get(
            sitting.rsplit("/", 1)[0] + "/" + replacement + "/eligibility", headers=headers[0]
        ).status_code
        == 404
    )


def test_unregistered_candidate_sees_empty_inbox_and_bounded_pagination(invitation_setup):
    db, _, _, _, _, _, _, _, inbox = invitation_setup
    with db.admin_engine.begin() as c:
        context(c, db)
        c.execute(
            update(Membership)
            .where(Membership.tenant_id == db.ids["tenant_a"], Membership.user_id == db.ids["outsider"])
            .values(role="candidate")
        )
    headers = db.login("outsider")
    response = db.client.get(inbox, headers=headers)
    assert (
        response.status_code == 200
        and response.json()["items"] == []
        and response.json()["has_more"] is False
    )
    assert db.client.get(inbox + "?limit=101", headers=headers).status_code == 422
    assert db.client.get(inbox + "/" + str(uuid4()), headers=headers).status_code == 404


def test_acceptance_and_accommodation_amendment_serialize(invitation_setup):
    db, staff, _, _, sitting, _, rows, headers, inbox = invitation_setup
    with ThreadPoolExecutor(max_workers=2) as executor:
        acknowledging = executor.submit(accept, invitation_setup)
        amendment = executor.submit(
            db.client.put,
            sitting + "/registrations/" + rows[0]["id"] + "/changes/" + str(uuid4()),
            headers=staff,
            json={
                "expected_revision": 1,
                "action": "amend_accommodation",
                "extra_minutes": 20,
                "reason": "Synthetic extra-time review",
            },
        )
        assert amendment.result().status_code == 200
        response = acknowledging.result()
    assert response.status_code == 200, response.text
    assert response.json()["registration_revision"] in (1, 2)
    item = db.client.get(inbox, headers=headers[0]).json()["items"][0]
    assert item["allowed_minutes"] == 50 and item["registration_revision"] == 2
