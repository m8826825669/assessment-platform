from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import AuditRecord, ConsumerReceipt, Membership, OutboxDelivery, OutboxEvent
from app.outbox.worker import CONSUMER, Claim, PermanentFailure, receipt_handler

pytestmark = pytest.mark.integration


def context(session, tenant):
    session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)})


def patch_member(db, headers, **body):
    return db.client.patch(
        f"/api/v1/tenants/{db.ids['tenant_a']}/memberships/{db.ids['membership_candidate']}",
        headers=headers,
        json=body,
    )


def expire_claim(db, identifier, *, exhausted=False):
    with db.worker_database.sessions() as session, session.begin():
        job = session.get(OutboxDelivery, identifier)
        job.lease_expires_at = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
        if exhausted:
            job.attempts = job.max_attempts


def make_due(db, identifier):
    with db.worker_database.sessions() as session, session.begin():
        session.get(OutboxDelivery, identifier).available_at = session.scalar(
            select(func.clock_timestamp())
        ) - timedelta(seconds=1)


def test_membership_change_audit_and_outbox_commit_together(security_database):
    db = security_database
    headers = db.login("admin_a")
    response = patch_member(db, headers, role="reviewer")
    assert response.status_code == 200
    with Session(db.admin_engine) as session:
        context(session, db.ids["tenant_a"])
        audit = session.scalars(select(AuditRecord).where(AuditRecord.action == "membership.changed")).one()
        assert audit.before_state == {
            "role": "candidate",
            "status": "active",
            "user_id": str(db.ids["candidate"]),
        }
        assert audit.after_state["role"] == "reviewer"
        assert str(audit.request_id) == response.headers["x-request-id"]
        envelope = session.scalars(select(OutboxEvent).where(OutboxEvent.audit_id == audit.id)).one()
        assert envelope.tenant_id == audit.tenant_id
        assert envelope.payload["after"] == audit.after_state
        assert session.get(OutboxDelivery, envelope.id).status == "pending"


def test_failed_enqueue_rolls_back_business_and_audit(security_database, monkeypatch):
    from app.audit import service

    db = security_database
    headers = db.login("admin_a")
    original = service.OutboxDelivery

    def invalid_delivery(**values):
        return original(**values, max_attempts=0)

    monkeypatch.setattr(service, "OutboxDelivery", invalid_delivery)
    assert patch_member(db, headers, role="reviewer").status_code == 503
    with Session(db.admin_engine) as session:
        context(session, db.ids["tenant_a"])
        assert session.get(Membership, db.ids["membership_candidate"]).role == "candidate"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditRecord)
                .where(AuditRecord.action == "membership.changed")
            )
            == 0
        )
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 1  # Successful login only.


def test_tenant_admin_audit_read_is_scoped_and_candidate_is_denied(security_database):
    db = security_database
    admin = db.login("admin_a")
    assert patch_member(db, admin, role="reviewer").status_code == 200
    path = f"/api/v1/tenants/{db.ids['tenant_a']}/audit"
    response = db.client.get(path, headers=admin)
    assert response.status_code == 200
    assert len(response.json()) == 1  # Global login audit is never exposed in tenant history.
    assert all(row["tenant_id"] == str(db.ids["tenant_a"]) for row in response.json())
    candidate = db.login("candidate")
    assert db.client.get(path, headers=candidate).status_code == 403
    other = db.login("admin_b")
    assert db.client.get(path, headers=other).status_code == 404


def test_audit_and_payload_never_store_passwords_or_raw_tokens(security_database):
    db = security_database
    headers = db.login("admin_a")
    with Session(db.admin_engine) as session:
        audits = session.scalars(select(AuditRecord)).all()
        envelopes = session.scalars(select(OutboxEvent)).all()
        serialized = str([(row.before_state, row.after_state) for row in audits]) + str(
            [row.payload for row in envelopes]
        )
        assert db.password not in serialized
        assert headers["Authorization"].split()[1] not in serialized
        assert "admin_a@example.test" not in serialized
        assert "$argon2" not in serialized


def test_successful_processing_has_one_receipt_and_terminal_ack(outbox_database):
    db = outbox_database
    db.login("admin_a")
    claim = db.worker.claim()
    assert db.worker.process(claim) == "delivered"
    assert db.worker.process(claim) == "stale"
    with db.worker_database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ConsumerReceipt)) == 1
        job = session.get(OutboxDelivery, claim.event_id)
        assert job.status == "delivered" and job.lease_token is None
        assert job.attempts == 1


def test_handler_effect_and_ack_rollback_before_retry(outbox_database):
    db = outbox_database
    db.login("admin_a")
    claim = db.worker.claim()

    def failing(session, event):
        receipt_handler(session, event)
        raise RuntimeError("sensitive failure text must not persist")

    assert db.worker.process(claim, failing) == "pending"
    with db.worker_database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ConsumerReceipt)) == 0
        job = session.get(OutboxDelivery, claim.event_id)
        assert job.last_error_code == "handler_failed"
        assert job.attempts == 1
    make_due(db, claim.event_id)
    next_claim = db.worker.claim()
    assert db.worker.process(next_claim) == "delivered"
    with db.worker_database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ConsumerReceipt)) == 1


def test_duplicate_dispatch_uses_existing_receipt(outbox_database):
    db = outbox_database
    db.login("admin_a")
    claim = db.worker.claim()
    with db.worker_database.sessions() as session, session.begin():
        receipt_handler(session, session.get(OutboxEvent, claim.event_id))
    assert db.worker.process(claim) == "delivered"
    with db.worker_database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ConsumerReceipt)) == 1


def test_receipt_hash_mismatch_is_dead_lettered(outbox_database):
    db = outbox_database
    db.login("admin_a")
    claim = db.worker.claim()
    with db.worker_database.sessions() as session, session.begin():
        session.add(ConsumerReceipt(consumer=CONSUMER, event_id=claim.event_id, payload_hash="0" * 64))
    assert db.worker.process(claim) == "dead"


def test_expired_claim_is_recovered_and_old_token_cannot_ack(outbox_database):
    db = outbox_database
    db.login("admin_a")
    old = db.worker.claim()
    expire_claim(db, old.event_id)
    new = db.worker.claim()
    assert new.event_id == old.event_id and new.token != old.token
    assert db.worker.process(old) == "stale"
    assert db.worker.process(new) == "delivered"


def test_expiry_during_handler_rolls_back_receipt(outbox_database):
    db = outbox_database
    db.login("admin_a")
    claim = db.worker.claim()

    def expire_inside_transaction(session, event):
        receipt_handler(session, event)
        job = session.get(OutboxDelivery, event.id)
        job.lease_expires_at = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)

    assert db.worker.process(claim, expire_inside_transaction) == "stale"
    with db.worker_database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ConsumerReceipt)) == 0
        assert session.get(OutboxDelivery, claim.event_id).status == "processing"


def test_expired_final_attempt_becomes_dead(outbox_database):
    db = outbox_database
    db.login("admin_a")
    claim = db.worker.claim()
    expire_claim(db, claim.event_id, exhausted=True)
    assert db.worker.claim() is None
    with db.worker_database.sessions() as session:
        assert session.get(OutboxDelivery, claim.event_id).status == "dead"
        assert session.get(OutboxDelivery, claim.event_id).last_error_code == "lease_exhausted"


def test_repeated_failure_stops_at_attempt_budget(outbox_database):
    db = outbox_database
    db.login("admin_a")

    def fail(session, event):
        raise RuntimeError("not stored")

    for attempt in range(1, 6):
        claim = db.worker.claim()
        assert claim is not None
        assert db.worker.process(claim, fail) == ("dead" if attempt == 5 else "pending")
        if attempt < 5:
            make_due(db, claim.event_id)
    assert db.worker.claim() is None


def test_permanent_contract_failure_has_no_receipt(outbox_database):
    db = outbox_database
    db.login("admin_a")
    claim = db.worker.claim()

    def unsupported(session, event):
        invalid = OutboxEvent(
            id=event.id,
            audit_id=event.audit_id,
            tenant_id=event.tenant_id,
            scope_key=event.scope_key,
            payload=dict(event.payload),
            event_type="unsupported.v99",
        )
        receipt_handler(session, invalid)

    assert db.worker.process(claim, unsupported) == "dead"
    with db.worker_database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ConsumerReceipt)) == 0


def test_parallel_claims_do_not_take_same_job(outbox_database):
    db = outbox_database
    db.login("admin_a")
    db.login("admin_b")
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: db.worker.claim(), range(2)))
    assert len({claim.event_id for claim in claims}) == 2
    assert all(db.worker.process(claim) == "delivered" for claim in claims)


def test_wrong_lease_token_has_no_effect(outbox_database):
    db = outbox_database
    db.login("admin_a")
    claim = db.worker.claim()
    assert db.worker.process(Claim(claim.event_id, uuid4())) == "stale"
    assert db.worker.process(claim) == "delivered"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_records SET action='tampered'",
        "DELETE FROM audit_records",
        "TRUNCATE audit_records",
        "UPDATE outbox_events SET event_type='tampered'",
        "SELECT * FROM outbox_deliveries",
        "SELECT * FROM consumer_receipts",
        "DELETE FROM outbox_events",
    ],
)
def test_api_cannot_rewrite_audit_or_run_worker_operations(security_database, statement):
    with pytest.raises(DBAPIError), security_database.runtime_engine.begin() as connection:
        connection.execute(text(statement))


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM users",
        "SELECT * FROM auth_sessions",
        "SELECT * FROM memberships",
        "UPDATE consumer_receipts SET payload_hash='tampered'",
        "DELETE FROM consumer_receipts",
        "UPDATE outbox_events SET event_type='tampered'",
        "CREATE TABLE forbidden_worker_table (id int)",
    ],
)
def test_worker_cannot_access_credentials_or_mutate_immutable_data(outbox_database, statement):
    with pytest.raises(DBAPIError), outbox_database.worker_database.engine.begin() as connection:
        connection.execute(text(statement))


def test_direct_audit_read_does_not_cross_tenant(security_database):
    db = security_database
    admin = db.login("admin_a")
    assert patch_member(db, admin, role="reviewer").status_code == 200
    with db.runtime_engine.begin() as connection:
        context(connection, db.ids["tenant_b"])
        assert connection.scalar(text("SELECT count(*) FROM audit_records")) == 0


def test_composite_fk_rejects_mismatched_audit_scope(security_database):
    db = security_database
    audit_id = uuid4()
    with Session(db.admin_engine) as session, session.begin():
        context(session, db.ids["tenant_a"])
        session.add(
            AuditRecord(
                id=audit_id,
                tenant_id=db.ids["tenant_a"],
                scope_key=str(db.ids["tenant_a"]),
                actor_kind="anonymous",
                action="membership.changed",
            )
        )
    with pytest.raises(DBAPIError) as captured, db.admin_engine.begin() as connection:
        context(connection, db.ids["tenant_b"])
        connection.execute(
            text(
                "INSERT INTO outbox_events (id,audit_id,tenant_id,scope_key,event_type,payload) VALUES (:id,:audit,:tenant,:scope,'audit.recorded.v1','{}'::jsonb)"
            ),
            {
                "id": uuid4(),
                "audit": audit_id,
                "tenant": db.ids["tenant_b"],
                "scope": str(db.ids["tenant_b"]),
            },
        )
    assert captured.value.orig.diag.constraint_name == "fk_outbox_events_audit_id_audit_records"


def test_reviewed_dead_event_requeue_is_audited_and_consumable(outbox_database, monkeypatch):
    from types import SimpleNamespace

    from app import manage
    from app.config import Settings

    db = outbox_database
    db.login("admin_a")
    claim = db.worker.claim()

    def permanent(session, event):
        raise PermanentFailure("test only")

    assert db.worker.process(claim, permanent) == "dead"
    settings = Settings(
        _env_file=None,
        database_url=db.runtime_url,
        migration_database_url=db.admin_engine.url.render_as_string(hide_password=False),
    )
    monkeypatch.setattr(manage, "Settings", lambda: settings)
    manage.run(SimpleNamespace(command="requeue-outbox", event=claim.event_id, reason_code="handler_fixed"))
    with Session(db.admin_engine) as session:
        audit = session.scalars(
            select(AuditRecord).where(AuditRecord.action == "operator.outbox_requeued")
        ).one()
        assert audit.before_state == {"status": "dead", "attempts": 1}
        assert audit.after_state == {"status": "pending", "attempts": 0, "reason_code": "handler_fixed"}
    assert db.worker.run_once()["delivered"] == 2
    with db.worker_database.sessions() as session:
        assert session.get(OutboxDelivery, claim.event_id).status == "delivered"


def test_live_pending_event_cannot_be_requeued(outbox_database, monkeypatch):
    from types import SimpleNamespace

    from app import manage
    from app.config import Settings

    db = outbox_database
    db.login("admin_a")
    with Session(db.admin_engine) as session:
        event_id = session.scalars(select(OutboxEvent.id)).one()
    settings = Settings(
        _env_file=None,
        database_url=db.runtime_url,
        migration_database_url=db.admin_engine.url.render_as_string(hide_password=False),
    )
    monkeypatch.setattr(manage, "Settings", lambda: settings)
    with pytest.raises(ValueError, match="Only a dead"):
        manage.run(SimpleNamespace(command="requeue-outbox", event=event_id, reason_code="handler_fixed"))
    with db.worker_database.sessions() as session:
        assert session.get(OutboxDelivery, event_id).status == "pending"


def test_worker_cli_processes_without_printing_credentials(outbox_database, monkeypatch, capsys):
    from app import worker as cli
    from app.config import Settings

    db = outbox_database
    db.login("admin_a")
    settings = Settings(
        _env_file=None,
        database_url=db.runtime_url,
        worker_database_url=db.worker_database.engine.url.render_as_string(hide_password=False),
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr("sys.argv", ["worker", "--once", "--limit", "10"])
    cli.main()
    output = capsys.readouterr().out
    assert '"delivered": 1' in output
    assert db.worker_database.engine.url.password not in output
    assert "postgresql" not in output


def test_api_credentials_cannot_be_used_as_worker(outbox_database, monkeypatch):
    from app import worker as cli
    from app.config import Settings

    db = outbox_database
    db.login("admin_a")
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(_env_file=None, database_url=db.runtime_url, worker_database_url=db.runtime_url),
    )
    monkeypatch.setattr("sys.argv", ["worker", "--once"])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1
    with db.worker_database.sessions() as session:
        assert session.scalars(select(OutboxDelivery.status)).one() == "pending"


def test_missing_new_runtime_grants_are_reported_before_business_writes(security_database):
    import psycopg
    from psycopg import sql

    db = security_database
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL("REVOKE INSERT ON audit_records FROM {}").format(
                sql.Identifier(db.runtime_engine.url.username)
            )
        )
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"]["runtime_role"] == "missing_grants"
    response = db.client.post(
        "/api/v1/auth/login", json={"email": "admin_a@example.test", "password": db.password}
    )
    assert response.status_code == 503
    with Session(db.admin_engine) as session:
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


@pytest.mark.parametrize("grant_name,role_source", [("grant_worker", "runtime"), ("grant_runtime", "worker")])
def test_provisioning_refuses_mixing_api_and_worker_roles(outbox_database, grant_name, role_source):
    import psycopg

    from app.db import provisioning

    db = outbox_database
    role = (
        db.runtime_engine.url.username if role_source == "runtime" else db.worker_database.engine.url.username
    )
    dsn = db.admin_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as connection:
        with pytest.raises(ValueError, match="separate"):
            getattr(provisioning, grant_name)(connection, role)
    assert db.client.get("/api/v1/ready").status_code == 200
