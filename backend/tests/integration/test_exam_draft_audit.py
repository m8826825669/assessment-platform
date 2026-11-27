"""ASM-01/GOV-01 atomic draft creation, safe retries and audit boundaries."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from test_question_review import context, path, prepare

from app.audit.service import clean_state

pytestmark = pytest.mark.integration


def counts(db, draft_id):
    with db.admin_engine.begin() as connection:
        context(connection, db)
        params = {"id": draft_id, "tenant": db.ids["tenant_a"]}
        return tuple(
            connection.scalar(text(query), params)
            for query in (
                "SELECT count(*) FROM exam_blueprint_drafts WHERE tenant_id=:tenant AND id=:id",
                "SELECT count(*) FROM audit_records WHERE tenant_id=:tenant AND subject_id=:id "
                "AND action='exam.draft_created'",
                "SELECT count(*) FROM outbox_events WHERE tenant_id=:tenant "
                "AND payload->>'subject_id'=CAST(:id AS text) AND payload->>'action'='exam.draft_created'",
                "SELECT count(*) FROM outbox_deliveries d JOIN outbox_events e ON e.id=d.event_id "
                "WHERE e.tenant_id=:tenant AND e.payload->>'subject_id'=CAST(:id AS text) "
                "AND e.payload->>'action'='exam.draft_created'",
            )
        )


def test_draft_audit_replay_conflict_and_concurrent_creation(security_database):
    db = security_database
    _, _, coordinator = prepare(db)
    draft_id = uuid4()
    url = path(db, "exam-blueprints", f"/drafts/{draft_id}")
    body = {"sections": []}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(db.client.put, url, headers=coordinator, json=body) for _ in range(2)]
        responses = [future.result(timeout=30) for future in futures]
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert counts(db, draft_id) == (1, 1, 1, 1)
    assert db.client.put(url, headers=coordinator, json=body).status_code == 200
    changed = {"sections": [{"version_ids": [], "minimum": 0, "maximum": 0}]}
    assert db.client.put(url, headers=coordinator, json=changed).status_code == 409
    assert db.client.get(url, headers=coordinator).json()["sections"] == []
    assert counts(db, draft_id) == (1, 1, 1, 1)


@pytest.mark.parametrize("table", ["audit_records", "outbox_events", "outbox_deliveries"])
def test_draft_audit_failure_rolls_back_everything(security_database, table):
    db = security_database
    _, _, coordinator = prepare(db)
    draft_id = uuid4()
    url = path(db, "exam-blueprints", f"/drafts/{draft_id}")
    engine = db.client.app.state.database.engine

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith("INSERT INTO " + table):
            raise SQLAlchemyError("Injected draft transaction failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = db.client.put(url, headers=coordinator, json={"sections": []})
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503, response.text
    assert db.client.get(url, headers=coordinator).status_code == 404
    assert counts(db, draft_id) == (0, 0, 0, 0)
    assert db.client.put(url, headers=coordinator, json={"sections": []}).status_code == 200
    assert counts(db, draft_id) == (1, 1, 1, 1)


def test_draft_creation_rejects_unprivileged_actor(security_database):
    db = security_database
    _, reviewer, _ = prepare(db)
    draft_id = uuid4()
    url = path(db, "exam-blueprints", f"/drafts/{draft_id}")
    assert db.client.put(url, headers=reviewer, json={"sections": []}).status_code == 403
    assert counts(db, draft_id) == (0, 0, 0, 0)


@pytest.mark.parametrize("field", ["content", "grading", "token", "email", "title"])
def test_draft_audit_rejects_private_snapshots(field):
    assert clean_state("exam.draft_created", {}) == {}
    with pytest.raises(ValueError, match="Unapproved"):
        clean_state("exam.draft_created", {field: "private"})
