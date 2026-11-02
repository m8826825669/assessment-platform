"""P2-006 real PostgreSQL atomic imports, receipts, scopes and retries."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from test_authoring_media import clean, context
from test_authoring_media import media_db as media_db
from test_media_storage_live import live_media as live_media
from test_question_taxonomy import term

from app.db.models import AuthSession, Membership, QuestionImportReceipt
from app.question_imports.contracts import MAX_BYTES, PROFILE

pytestmark = pytest.mark.integration
EXAMPLES = json.loads(
    (Path(__file__).resolve().parents[3] / "docs/QUESTION_CONTENT_EXAMPLES.json").read_text()
)


def path(db, suffix="", tenant="a"):
    return f"/api/v1/tenants/{db.ids['tenant_' + tenant]}/question-imports" + suffix


def payload(contents=None):
    return {
        "schema_version": PROFILE,
        "items": [
            {"reference": "row_" + str(i), "title": "Imported fixture " + str(i), "content": deepcopy(c)}
            for i, c in enumerate(contents or EXAMPLES[:2])
        ],
    }


def commit(db, who, body, key=None, tenant="a"):
    return db.client.post(
        path(db, tenant=tenant), headers={**who, "Idempotency-Key": str(key or uuid4())}, json=body
    )


def counts(db):
    with db.admin_engine.begin() as connection:
        context(connection, db)
        return {
            table: connection.scalar(text("SELECT count(*) FROM " + table))
            for table in [
                "questions",
                "question_versions",
                "question_version_taxa",
                "question_version_media",
                "question_import_receipts",
                "audit_records",
                "outbox_events",
                "outbox_deliveries",
            ]
        }


def set_role(db, role):
    with db.admin_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            update(Membership).where(Membership.id == db.ids["membership_candidate"]).values(role=role)
        )
    return db.login("candidate")


def test_preview_all_types_is_read_only_and_public_projection_only(security_database):
    db = security_database
    admin = db.login("admin_a")
    before = counts(db)
    response = db.client.post(path(db, "/preview"), headers=admin, json=payload(EXAMPLES))
    assert response.status_code == 200, response.text
    assert response.json()["item_count"] == 7 and response.json()["valid"] is True
    for secret in [
        "correct_option_id",
        "accepted_answers",
        "absolute_tolerance",
        "marker_guidance",
        "rubric",
    ]:
        assert secret not in response.text
    assert counts(db) == before


def test_atomic_all_type_commit_returns_immutable_owner_receipt(security_database):
    db = security_database
    admin = db.login("admin_a")
    before = counts(db)
    result = commit(db, admin, payload(EXAMPLES))
    assert result.status_code == 201, result.text
    receipt = result.json()
    assert receipt["item_count"] == 7 and receipt["created_as"] == "draft"
    assert len({x["question_id"] for x in receipt["items"]}) == 7
    assert db.client.get(path(db, "/" + receipt["batch_id"]), headers=admin).json() == receipt
    for mapping, content in zip(receipt["items"], EXAMPLES):
        question = db.client.get(
            f"/api/v1/tenants/{db.ids['tenant_a']}/questions/{mapping['question_id']}", headers=admin
        )
        assert question.status_code == 200 and question.json()["state"] == "draft"
        assert question.json()["version_id"] == mapping["version_id"]
        assert question.json()["content"]["kind"] == content["kind"]
    after = counts(db)
    assert after["questions"] - before["questions"] == 7
    assert after["question_versions"] - before["question_versions"] == 7
    assert after["question_import_receipts"] - before["question_import_receipts"] == 1
    assert after["audit_records"] - before["audit_records"] == 8
    assert after["outbox_deliveries"] - before["outbox_deliveries"] == 8
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(text("SELECT count(*) FROM question_review_events")) == 0
        assert connection.scalar(text("SELECT count(*) FROM question_selections")) == 0
        snapshot = connection.scalar(
            text("SELECT after_state::text FROM audit_records WHERE action='question.import_committed'")
        )
        assert set(json.loads(snapshot)) == {"batch_id", "item_count"}


def test_retry_has_identical_ids_and_response_without_new_writes_even_after_edit(security_database):
    db = security_database
    admin = db.login("admin_a")
    key = uuid4()
    body = payload()
    first = commit(db, admin, body, key)
    assert first.status_code == 201, first.text
    original = first.json()
    qid = original["items"][0]["question_id"]
    edited = db.client.post(
        f"/api/v1/tenants/{db.ids['tenant_a']}/questions/{qid}/versions",
        headers=admin,
        json={"expected_revision": 1, "title": "Later edit", "content": EXAMPLES[1]},
    )
    assert edited.status_code == 201
    before = counts(db)
    replay = commit(db, admin, body, key)
    assert replay.status_code == 200 and replay.json() == original
    assert counts(db) == before


@pytest.mark.parametrize("change", ["title", "answer", "reference"])
def test_reused_key_with_changed_payload_conflicts_without_mutation(security_database, change):
    db = security_database
    admin = db.login("admin_a")
    key = uuid4()
    body = payload()
    assert commit(db, admin, body, key).status_code == 201
    before = counts(db)
    changed = deepcopy(body)
    if change == "answer":
        content = changed["items"][0]["content"]
        content["correct_option_id"] = next(
            o["id"] for o in content["options"] if o["id"] != content["correct_option_id"]
        )
    else:
        changed["items"][0][change] = "changed"
    response = commit(db, admin, changed, key)
    assert response.status_code == 409 and response.json()["code"] == "import_conflict"
    assert counts(db) == before


def test_duplicate_concurrent_imports_create_one_batch(security_database):
    db = security_database
    admin = db.login("admin_a")
    key = uuid4()
    body = payload()
    before = counts(db)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: commit(db, admin, body, key), range(2)))
    assert sorted(r.status_code for r in results) == [200, 201]
    assert results[0].json() == results[1].json()
    after = counts(db)
    assert (
        after["questions"] - before["questions"] == 2
        and after["question_import_receipts"] - before["question_import_receipts"] == 1
    )


def test_new_key_is_an_explicit_new_import_and_actor_keys_are_separate(security_database):
    db = security_database
    admin = db.login("admin_a")
    author = set_role(db, "author")
    key = uuid4()
    body = payload()
    first = commit(db, admin, body, key)
    second = commit(db, author, body, key)
    third = commit(db, admin, body)
    assert [x.status_code for x in [first, second, third]] == [201, 201, 201]
    assert len({x.json()["batch_id"] for x in [first, second, third]}) == 3
    # Even an institution admin cannot use a different actor's private receipt lookup namespace.
    assert db.client.get(path(db, "/" + second.json()["batch_id"]), headers=admin).status_code == 404
    with db.runtime_engine.begin() as connection:
        context(connection, db, "candidate")
        assert connection.scalar(select(QuestionImportReceipt.id)) == UUID(second.json()["batch_id"])


@pytest.mark.parametrize("role", ["candidate", "invigilator", "examiner", "reviewer", "coordinator"])
def test_non_authoring_roles_cannot_preview_commit_or_read_receipts(security_database, role):
    db = security_database
    admin = db.login("admin_a")
    saved = commit(db, admin, payload()).json()
    who = set_role(db, role)
    assert db.client.post(path(db, "/preview"), headers=who, json=payload()).status_code == 403
    assert commit(db, who, payload()).status_code == 403
    assert db.client.get(path(db, "/" + saved["batch_id"]), headers=who).status_code == 403


def test_foreign_receipts_and_tenant_membership_are_not_discoverable(security_database):
    db = security_database
    admin = db.login("admin_a")
    other = db.login("admin_b")
    key = uuid4()
    one = commit(db, admin, payload(), key)
    two = commit(db, other, payload(), key, tenant="b")
    assert one.status_code == two.status_code == 201
    assert db.client.get(path(db, "/" + two.json()["batch_id"]), headers=admin).status_code == 404
    assert db.client.get(path(db, "/" + str(uuid4())), headers=admin).status_code == 404
    assert commit(db, admin, payload(), tenant="b").status_code == 404


@pytest.mark.parametrize("bad_reference", ["taxonomy", "media"])
def test_bad_later_reference_rolls_back_every_earlier_row_and_key_remains_reusable(
    security_database, bad_reference
):
    db = security_database
    admin = db.login("admin_a")
    body = payload()
    key = uuid4()
    before = counts(db)
    invalid = deepcopy(body)
    invalid["items"][-1][bad_reference + "_ids"] = [str(uuid4())]
    result = commit(db, admin, invalid, key)
    # Media is disabled on this fixture; unknown media therefore fails closed as unavailable.
    assert result.status_code == (404 if bad_reference == "taxonomy" else 503), result.text
    assert counts(db) == before
    assert commit(db, admin, body, key).status_code == 201


@pytest.mark.parametrize("failure_at", ["second_question", "receipt", "batch_audit", "outbox"])
def test_all_business_receipt_audit_and_outbox_rows_roll_back_together(security_database, failure_at):
    db = security_database
    admin = db.login("admin_a")
    body = payload()
    key = uuid4()
    before = counts(db)
    engine = db.client.app.state.database.engine
    seen = 0

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        nonlocal seen
        if statement.startswith("INSERT INTO questions"):
            seen += 1
            if failure_at == "second_question" and seen == 2:
                raise SQLAlchemyError("Injected failure")
        if failure_at == "receipt" and statement.startswith("INSERT INTO question_import_receipts"):
            raise SQLAlchemyError("Injected failure")
        if failure_at == "batch_audit" and statement.startswith("INSERT INTO audit_records"):
            values = parameters if isinstance(parameters, dict) else {}
            if values.get("action") == "question.import_committed":
                raise SQLAlchemyError("Injected failure")
        if failure_at == "outbox" and statement.startswith("INSERT INTO outbox_deliveries") and seen == 2:
            raise SQLAlchemyError("Injected failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        result = commit(db, admin, body, key)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert result.status_code == 503, result.text
    assert counts(db) == before
    assert commit(db, admin, body, key).status_code == 201


@pytest.mark.parametrize("revocation,status", [("role", 403), ("session", 401)])
def test_import_authority_is_rechecked_after_waiting_for_mutation_lock(security_database, revocation, status):
    db = security_database
    author = set_role(db, "author")
    reached = Event()
    engine = db.client.app.state.database.engine

    def observe(connection, cursor, statement, parameters, ctx, executemany):
        if "FROM institutions" in statement and "FOR UPDATE" in statement:
            reached.set()

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with db.admin_engine.begin() as connection:
                context(connection, db)
                connection.execute(
                    text("SELECT id FROM institutions WHERE id=:id FOR UPDATE"), {"id": db.ids["tenant_a"]}
                )
                pending = executor.submit(commit, db, author, payload())
                assert reached.wait(3)
                if revocation == "role":
                    connection.execute(
                        update(Membership)
                        .where(Membership.id == db.ids["membership_candidate"])
                        .values(role="candidate")
                    )
                else:
                    connection.execute(
                        update(AuthSession)
                        .where(AuthSession.user_id == db.ids["candidate"])
                        .values(revoked_at=text("clock_timestamp()"))
                    )
            assert pending.result(timeout=8).status_code == status
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert counts(db)["questions"] == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE question_import_receipts SET request_hash='changed'",
        "DELETE FROM question_import_receipts",
        "TRUNCATE question_import_receipts",
    ],
)
def test_runtime_cannot_rewrite_or_erase_success_receipts(security_database, statement):
    db = security_database
    admin = db.login("admin_a")
    assert commit(db, admin, payload()).status_code == 201
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db)
        connection.execute(text(statement))


def test_database_rejects_receipt_binding_existing_committed_versions(security_database):
    db = security_database
    admin = db.login("admin_a")
    receipt = commit(db, admin, payload()).json()
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            QuestionImportReceipt.__table__.insert().values(
                id=uuid4(),
                tenant_id=db.ids["tenant_a"],
                actor_user_id=db.ids["admin_a"],
                idempotency_key=uuid4(),
                profile=PROFILE,
                request_hash="a" * 64,
                item_count=2,
                result=receipt["items"],
            )
        )


def test_worker_consumes_safe_import_event_without_receipt_grants(outbox_database):
    db = outbox_database
    admin = db.login("admin_a")
    result = commit(db, admin, payload())
    assert result.status_code == 201, result.text
    assert db.worker.run_once(100).get("delivered") == 4
    assert db.worker.run_once(100) == {}
    with pytest.raises(DBAPIError), db.worker_database.engine.begin() as connection:
        connection.execute(text("SELECT * FROM question_import_receipts"))


@pytest.mark.parametrize("stage", ["pending", "clean_missing", "foreign"])
def test_import_media_references_fail_atomically(media_db, stage):
    db = media_db
    admin = db.login("admin_a")
    body = payload()
    if stage == "pending":
        from test_authoring_media import reserve

        asset = reserve(db, admin)
    else:
        asset = clean(db, admin)
    if stage == "clean_missing":
        db.client.app.state.media.store.objects.clear()
    if stage == "foreign":
        body["items"][-1]["media_ids"] = [str(uuid4())]
    else:
        body["items"][-1]["media_ids"] = [asset["asset_id"]]
    before = counts(db)
    result = commit(db, admin, body)
    assert result.status_code == {"pending": 409, "clean_missing": 503, "foreign": 404}[stage], result.text
    assert counts(db) == before


def test_live_media_taxonomy_preview_commit_and_replay_after_catalogue_retirement(live_media):
    db, _, _, _ = live_media
    admin = db.login("admin_a")
    asset = clean(db, admin)
    subject = term(db, admin, "subject", "math", "Mathematics")
    topic = term(db, admin, "topic", "algebra", "Algebra", subject)
    body = payload(EXAMPLES[:1])
    body["items"][0].update(taxonomy_ids=[topic["id"]], media_ids=[asset["asset_id"]])
    before = counts(db)
    preview = db.client.post(path(db, "/preview"), headers=admin, json=body)
    assert preview.status_code == 200 and preview.json()["items"][0]["taxonomy_count"] == 2, preview.text
    assert counts(db) == before
    key = uuid4()
    first = commit(db, admin, body, key)
    assert first.status_code == 201, first.text
    question = db.client.get(
        f"/api/v1/tenants/{db.ids['tenant_a']}/questions/{first.json()['items'][0]['question_id']}",
        headers=admin,
    )
    assert (
        question.json()["state"] == "draft" and question.json()["media"][0]["asset_id"] == asset["asset_id"]
    )
    retired = db.client.patch(
        f"/api/v1/tenants/{db.ids['tenant_a']}/taxonomy/{topic['id']}",
        headers=admin,
        json={"expected_revision": 1, "state": "retired"},
    )
    assert retired.status_code == 200
    before = counts(db)
    replay = commit(db, admin, body, key)
    assert replay.status_code == 200 and replay.json() == first.json() and counts(db) == before
    assert commit(db, admin, body).status_code == 404


@pytest.mark.parametrize(
    "body,headers,status",
    [
        (b'{"secret":1,"secret":2}', {"Content-Type": "application/json"}, 422),
        (b"not-json", {"Content-Type": "text/plain"}, 415),
        (b"x" * (MAX_BYTES + 1), {"Content-Type": "application/json"}, 413),
        (b"{", {"Content-Type": "application/json"}, 422),
    ],
)
def test_http_import_parser_rejects_bad_documents_without_writes(security_database, body, headers, status):
    db = security_database
    admin = db.login("admin_a")
    before = counts(db)
    response = db.client.post(path(db, "/preview"), headers={**admin, **headers}, content=body)
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store" and counts(db) == before


def test_http_errors_never_echo_scoring_input_or_unknown_property_names(security_database):
    db = security_database
    admin = db.login("admin_a")
    body = payload()
    body["items"][0]["PRIVATE_KEY_NAME"] = "PRIVATE_ANSWER_VALUE"
    response = commit(db, admin, body)
    assert response.status_code == 422 and "PRIVATE" not in response.text
    assert counts(db)["questions"] == 0


def test_actual_foreign_catalogue_and_media_are_rejected_without_partial_import(media_db):
    db = media_db
    admin = db.login("admin_a")
    other = db.login("admin_b")
    remote_term = db.client.post(
        f"/api/v1/tenants/{db.ids['tenant_b']}/taxonomy",
        headers=other,
        json={"kind": "tag", "code": "foreign", "label": "Other institution"},
    )
    assert remote_term.status_code == 201, remote_term.text
    remote_media = db.client.post(
        f"/api/v1/tenants/{db.ids['tenant_b']}/media",
        headers=other,
        json={"filename": "foreign.png", "mime_type": "image/png", "description": "Other institution image"},
    )
    assert remote_media.status_code == 201, remote_media.text
    for field, identifier in [
        ("taxonomy_ids", remote_term.json()["id"]),
        ("media_ids", remote_media.json()["asset_id"]),
    ]:
        body = payload()
        body["items"][-1][field] = [identifier]
        before = counts(db)
        response = commit(db, admin, body)
        assert response.status_code == 404, response.text
        assert counts(db) == before


def test_receipt_guard_treats_uppercase_uuid_aliases_as_duplicate_identifiers(security_database):
    db = security_database
    admin = db.login("admin_a")
    before = counts(db)

    def tamper(mapper, connection, target):
        target.result[1]["question_id"] = target.result[0]["question_id"].upper()
        target.result[1]["version_id"] = target.result[0]["version_id"].upper()

    event.listen(QuestionImportReceipt, "before_insert", tamper)
    try:
        response = commit(db, admin, payload())
    finally:
        event.remove(QuestionImportReceipt, "before_insert", tamper)
    assert response.status_code == 409, response.text
    assert counts(db) == before
