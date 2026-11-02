from copy import deepcopy
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.audit.service import ACTIONS, clean_state, record
from app.db.models import AuditRecord, OutboxDelivery, OutboxEvent
from app.outbox.worker import PermanentFailure, Worker, payload_hash, retry_delay, validate_event
from app.request_context import request_id


def event():
    event_id, audit_id = uuid4(), uuid4()
    return OutboxEvent(
        id=event_id,
        audit_id=audit_id,
        tenant_id=None,
        scope_key="global",
        event_type="audit.recorded.v1",
        payload={
            "schema_version": 1,
            "event_id": str(event_id),
            "audit_id": str(audit_id),
            "tenant_id": None,
            "action": "login.succeeded",
            "subject_id": None,
            "request_id": None,
            "before": {},
            "after": {},
        },
    )


@pytest.mark.parametrize(
    "field", ["password", "password_hash", "access_token", "email", "raw_request", "authorization"]
)
def test_secrets_and_personal_fields_are_rejected_by_audit_schema(field):
    with pytest.raises(ValueError):
        clean_state("membership.changed", {field: "must-not-store"})


def test_audit_snapshots_are_copied_and_ids_canonicalized():
    user = uuid4()
    original = {"role": "candidate", "status": "active", "user_id": user}
    cleaned = clean_state("membership.changed", original)
    assert cleaned["user_id"] == str(user)
    assert original["user_id"] == user


@pytest.mark.parametrize("action", list(ACTIONS))
def test_registered_empty_snapshot_is_accepted(action):
    assert clean_state(action, {}) == {}


@pytest.mark.parametrize("snapshot", [{"role": "root"}, {"status": "unknown"}, {"user_id": "invalid"}])
def test_invalid_membership_snapshots_are_rejected(snapshot):
    with pytest.raises(ValueError):
        clean_state("membership.changed", snapshot)


def test_unregistered_action_is_rejected():
    with pytest.raises(ValueError):
        clean_state("password=" + "secret", {})


def test_audit_record_and_outbox_are_staged_without_committing():
    session = MagicMock()
    correlation = uuid4()
    token = request_id.set(correlation)
    try:
        identifier = record(session, "login.succeeded", actor=uuid4())
    finally:
        request_id.reset(token)
    rows = [call.args[0] for call in session.add.call_args_list]
    assert [type(row) for row in rows] == [AuditRecord, OutboxEvent, OutboxDelivery]
    audit, envelope, delivery = rows
    assert audit.request_id == correlation
    assert envelope.audit_id == audit.id
    assert envelope.id == delivery.event_id == identifier
    assert envelope.payload["request_id"] == str(correlation)
    session.commit.assert_not_called()
    assert session.flush.call_count == 3


def test_failed_audit_flush_never_stages_a_successful_delivery():
    session = MagicMock()
    session.flush.side_effect = SQLAlchemyError("do not echo this")
    with pytest.raises(SQLAlchemyError):
        record(session, "login.succeeded")
    assert session.add.call_count == 1
    session.commit.assert_not_called()


def test_event_hash_ignores_json_key_order():
    first = event()
    second = deepcopy(first)
    second.payload = dict(reversed(list(first.payload.items())))
    assert payload_hash(first) == payload_hash(second)


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2},
        {"event_id": str(uuid4())},
        {"audit_id": str(uuid4())},
        {"tenant_id": str(uuid4())},
        {"request_id": "invalid"},
        {"subject_id": "invalid"},
        {"unexpected_secret": "not allowed"},
        {"before": {"password": "not allowed"}},
    ],
)
def test_event_contract_rejects_mismatch_and_sensitive_data(change):
    envelope = event()
    envelope.payload = {**envelope.payload, **change}
    with pytest.raises(PermanentFailure):
        validate_event(envelope)


@pytest.mark.parametrize("attempt,expected", [(1, 2), (2, 4), (5, 32), (20, 3600)])
def test_retries_use_bounded_backoff(attempt, expected):
    assert retry_delay(attempt) == expected


@pytest.mark.parametrize("attempt", [0, 21])
def test_invalid_retry_attempt_is_rejected(attempt):
    with pytest.raises(ValueError):
        retry_delay(attempt)


@pytest.mark.parametrize("lease", [0, 601])
def test_worker_rejects_unbounded_lease_policy(lease):
    with pytest.raises(ValueError):
        Worker(MagicMock(), lease_seconds=lease)


def test_worker_configuration_preserves_existing_api_and_migration_credentials(tmp_path):
    from dotenv import dotenv_values

    from app.manage import configure_keys

    path = tmp_path / ".env"
    original = b"ASSESSMENT_DATABASE_URL=api-private\nASSESSMENT_MIGRATION_DATABASE_URL=owner-private\n"
    path.write_bytes(original)
    configure_keys(path, {"ASSESSMENT_WORKER_DATABASE_URL": "worker-private"}, ".env.pre-p1-004")
    values = dotenv_values(path, encoding="utf-8-sig")
    assert values["ASSESSMENT_DATABASE_URL"] == "api-private"
    assert values["ASSESSMENT_MIGRATION_DATABASE_URL"] == "owner-private"
    assert values["ASSESSMENT_WORKER_DATABASE_URL"] == "worker-private"
    assert (tmp_path / ".env.pre-p1-004").read_bytes() == original
