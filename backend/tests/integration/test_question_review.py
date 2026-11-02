"""QBK-01/IAM-01/TEN-01/GOV-01 real PostgreSQL review/projection boundaries."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.db.models import AuthSession, Membership, QuestionReviewEvent, QuestionSelection, QuestionVersion
from app.question_bank.contracts import candidate_view, validate_content

pytestmark = pytest.mark.integration
EXAMPLES = json.loads(
    (Path(__file__).resolve().parents[3] / "docs/QUESTION_CONTENT_EXAMPLES.json").read_text()
)


def path(db, kind="questions", suffix="", tenant="a"):
    return f"/api/v1/tenants/{db.ids['tenant_' + tenant]}/{kind}" + suffix


def context(connection, db, actor="admin_a", tenant="a"):
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(db.ids["tenant_" + tenant])}
    )
    connection.execute(
        text("SELECT set_config('app.actor_user_id', :actor, true)"), {"actor": str(db.ids[actor])}
    )


def prepare(db, role="reviewer"):
    with db.admin_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            Membership.__table__.insert().values(
                id=uuid4(), tenant_id=db.ids["tenant_a"], user_id=db.ids["outsider"], role=role
            )
        )
        connection.execute(
            update(Membership)
            .where(Membership.id == db.ids["membership_candidate"])
            .values(role="coordinator")
        )
    return db.login("admin_a"), db.login("outsider"), db.login("candidate")


def create(db, author, content=None):
    response = db.client.post(
        path(db), headers=author, json={"title": "Review fixture", "content": content or EXAMPLES[0]}
    )
    assert response.status_code == 201, response.text
    return response.json()


def review_path(db, row):
    return path(db, "question-reviews", f"/{row['question_id']}/versions/{row['version_id']}")


def command(row, action, reason=None):
    body = {
        "action": action,
        "expected_revision": row["revision"],
        "expected_review_revision": row["review_revision"],
        "content_hash": row["content_hash"],
    }
    if reason is not None:
        body["reason"] = reason
    return body


def decide(db, who, row, action, reason=None):
    return db.client.post(review_path(db, row), headers=who, json=command(row, action, reason))


def submit(db, author, row):
    response = decide(db, author, row, "submit")
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "in_review"
    return response.json()


def approve(db, reviewer, row):
    response = decide(db, reviewer, row, "approve")
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "approved"
    return response.json()


@pytest.mark.parametrize("content", EXAMPLES, ids=[item["kind"] for item in EXAMPLES])
def test_all_types_review_and_sql_projection_match_public_contract(security_database, content):
    db = security_database
    author, reviewer, coordinator = prepare(db)
    row = create(db, author, content)
    assert db.client.get(path(db, "question-selections"), headers=coordinator).json() == []
    row = submit(db, author, row)
    queue = db.client.get(path(db, "question-reviews"), headers=reviewer)
    assert queue.status_code == 200 and queue.json()[0]["version_id"] == row["version_id"]
    detail = db.client.get(review_path(db, row), headers=reviewer)
    assert detail.status_code == 200 and detail.json()["content"] == row["content"]
    row = approve(db, reviewer, row)
    selected = db.client.get(path(db, "question-selections", "/" + row["version_id"]), headers=coordinator)
    assert selected.status_code == 200, selected.text
    assert selected.json()["content"] == candidate_view(validate_content(row["content"]))
    assert set(selected.json()) == {"question_id", "version_id", "title", "content"}
    with db.runtime_engine.begin() as connection:
        context(connection, db, "candidate")
        assert connection.scalar(text("SELECT count(*) FROM question_versions")) == 0
        assert connection.scalar(text("SELECT count(*) FROM question_review_events")) == 0
        assert connection.scalar(text("SELECT count(*) FROM question_selections")) == 1
        assert connection.scalar(select(QuestionSelection.public_content)) == selected.json()["content"]


@pytest.mark.parametrize("role", ["admin", "reviewer"])
def test_originating_author_cannot_approve_own_version_after_role_change(security_database, role):
    db = security_database
    author = db.login("admin_a")
    row = submit(db, author, create(db, author))
    if role == "reviewer":
        with db.admin_engine.begin() as connection:
            context(connection, db)
            connection.execute(
                update(Membership).where(Membership.id == db.ids["membership_a"]).values(role="reviewer")
            )
    response = decide(db, author, row, "approve")
    assert response.status_code == 403 and response.json()["code"] == "review_self"
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(text("SELECT count(*) FROM question_selections")) == 0


def test_editor_and_submitter_cannot_approve_even_if_not_originating_author(security_database):
    db = security_database
    author, second, _ = prepare(db, "admin")
    row = create(db, author)
    response = db.client.post(
        path(db, suffix=f"/{row['question_id']}/versions"),
        headers=second,
        json={"title": "Edited by second admin", "expected_revision": 1, "content": EXAMPLES[1]},
    )
    assert response.status_code == 201
    row = submit(db, author, response.json())
    assert decide(db, second, row, "approve").status_code == 403
    # A submitter who did not edit is also ineligible.
    fresh = create(db, author)
    fresh = submit(db, second, fresh)
    assert decide(db, second, fresh, "approve").status_code == 403


def test_return_reason_is_private_and_correction_creates_a_fresh_draft(security_database):
    db = security_database
    author, reviewer, coordinator = prepare(db)
    first = submit(db, author, create(db, author))
    returned = decide(db, reviewer, first, "return", "Private editorial feedback")
    assert returned.status_code == 200 and returned.json()["state"] == "returned"
    old = db.client.get(review_path(db, first), headers=author)
    assert old.json()["decisions"][0]["reason"] == "Private editorial feedback"
    assert decide(db, author, returned.json(), "submit").status_code == 409
    edited = db.client.post(
        path(db, suffix=f"/{first['question_id']}/versions"),
        headers=author,
        json={"expected_revision": 1, "title": "Corrected", "content": EXAMPLES[1]},
    )
    assert (
        edited.status_code == 201
        and edited.json()["state"] == "draft"
        and edited.json()["review_revision"] == 0
    )
    assert db.client.get(path(db, "question-selections"), headers=coordinator).json() == []
    with db.admin_engine.begin() as connection:
        context(connection, db)
        payloads = (
            connection.execute(
                text(
                    "SELECT before_state::text || after_state::text FROM audit_records WHERE action LIKE 'question.review_%'"
                )
            )
            .scalars()
            .all()
        )
        assert "Private editorial feedback" not in "".join(payloads)
        assert "correct_option_id" not in "".join(payloads)


def test_revision_supersedes_pending_review_and_reviewer_cannot_read_new_draft(security_database):
    db = security_database
    author, reviewer, _ = prepare(db)
    original = submit(db, author, create(db, author))
    edited = db.client.post(
        path(db, suffix=f"/{original['question_id']}/versions"),
        headers=author,
        json={"expected_revision": 1, "title": "New private draft", "content": EXAMPLES[1]},
    ).json()
    old = db.client.get(review_path(db, original), headers=reviewer)
    assert old.status_code == 200 and old.json()["state"] == "superseded"
    assert db.client.get(path(db, "question-reviews"), headers=reviewer).json() == []
    assert db.client.get(review_path(db, edited), headers=reviewer).status_code == 404
    assert decide(db, reviewer, original, "approve").status_code == 409
    with db.runtime_engine.begin() as connection:
        context(connection, db, "outsider")
        assert connection.execute(select(QuestionVersion.id)).scalars().all() == [
            UUID(original["version_id"])
        ]


def test_approved_version_survives_new_draft_and_retirement_hides_only_new_selection(security_database):
    db = security_database
    author, reviewer, coordinator = prepare(db)
    first = approve(db, reviewer, submit(db, author, create(db, author)))
    public = db.client.get(path(db, "question-selections"), headers=coordinator).json()[0]
    edited = db.client.post(
        path(db, suffix=f"/{first['question_id']}/versions"),
        headers=author,
        json={"expected_revision": 1, "title": "Future draft", "content": EXAMPLES[1]},
    )
    assert edited.status_code == 201
    assert db.client.get(path(db, "question-selections"), headers=coordinator).json() == [public]
    old = db.client.get(review_path(db, first), headers=reviewer).json()
    retired = decide(db, reviewer, old, "retire", "Content needs updating")
    assert retired.status_code == 200 and retired.json()["state"] == "retired"
    assert db.client.get(path(db, "question-selections"), headers=coordinator).json() == []
    assert (
        db.client.get(
            path(db, "question-selections", "/" + first["version_id"]), headers=coordinator
        ).status_code
        == 404
    )
    with db.runtime_engine.begin() as connection:
        context(connection, db, "candidate")
        assert connection.scalar(select(QuestionSelection.public_content)) is None
    history = db.client.get(review_path(db, first), headers=author)
    assert history.json()["content"] == first["content"]


@pytest.mark.parametrize(
    "change", [{"expected_review_revision": 0}, {"expected_revision": 2}, {"content_hash": "b" * 64}]
)
def test_stale_or_mismatched_review_is_rejected_without_effect(security_database, change):
    db = security_database
    author, reviewer, _ = prepare(db)
    row = submit(db, author, create(db, author))
    response = db.client.post(
        review_path(db, row), headers=reviewer, json={**command(row, "approve"), **change}
    )
    assert response.status_code == 409 and response.json()["code"] == "review_conflict"
    assert db.client.get(review_path(db, row), headers=author).json()["review_revision"] == 1


def test_duplicate_concurrent_approvals_create_one_decision_and_selection(security_database):
    db = security_database
    author, reviewer, _ = prepare(db)
    row = submit(db, author, create(db, author))
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: decide(db, reviewer, row, "approve").status_code, range(2)))
    assert sorted(statuses) == [200, 409]
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert (
            connection.scalar(text("SELECT count(*) FROM question_review_events WHERE action='approve'")) == 1
        )
        assert connection.scalar(text("SELECT count(*) FROM question_selections")) == 1


def test_edit_approval_race_never_approves_replaced_content(security_database):
    db = security_database
    author, reviewer, coordinator = prepare(db)
    row = submit(db, author, create(db, author))

    def edit():
        return db.client.post(
            path(db, suffix=f"/{row['question_id']}/versions"),
            headers=author,
            json={"expected_revision": 1, "title": "Concurrent revision", "content": EXAMPLES[1]},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(edit)
        two = executor.submit(decide, db, reviewer, row, "approve")
        assert one.result() == 201
        approval = two.result()
    assert approval.status_code in [200, 409]
    selected = db.client.get(path(db, "question-selections"), headers=coordinator).json()
    assert (
        selected == []
        if approval.status_code == 409
        else [r["version_id"] for r in selected] == [row["version_id"]]
    )


@pytest.mark.parametrize("revocation,status", [("role", 403), ("session", 401)])
def test_review_authority_is_rechecked_after_waiting_for_lock(security_database, revocation, status):
    db = security_database
    author, reviewer, _ = prepare(db)
    row = submit(db, author, create(db, author))
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
                future = executor.submit(decide, db, reviewer, row, "approve")
                assert reached.wait(3)
                if revocation == "role":
                    connection.execute(
                        update(Membership)
                        .where(Membership.user_id == db.ids["outsider"])
                        .values(role="candidate")
                    )
                else:
                    connection.execute(
                        update(AuthSession)
                        .where(AuthSession.user_id == db.ids["outsider"])
                        .values(revoked_at=text("clock_timestamp()"))
                    )
            assert future.result(timeout=8).status_code == status
    finally:
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.parametrize("kind", ["question-reviews", "question-selections"])
def test_foreign_tenant_and_unauthorized_roles_cannot_use_review_or_selection(security_database, kind):
    db = security_database
    author, _, _ = prepare(db)
    assert db.client.get(path(db, kind, tenant="b"), headers=author).status_code == 404
    with db.admin_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            update(Membership).where(Membership.id == db.ids["membership_candidate"]).values(role="candidate")
        )
    candidate = db.login("candidate")
    assert db.client.get(path(db, kind), headers=candidate).status_code == 403


@pytest.mark.parametrize("table", ["question_review_events", "question_selections"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "TRUNCATE"])
def test_runtime_cannot_rewrite_review_or_public_snapshot(security_database, table, verb):
    db = security_database
    author, reviewer, _ = prepare(db)
    approve(db, reviewer, submit(db, author, create(db, author)))
    statement = (
        f"{verb} {table}"
        if verb == "TRUNCATE"
        else f"DELETE FROM {table}"
        if verb == "DELETE"
        else (
            f"UPDATE {table} SET reason='tampered'"
            if table == "question_review_events"
            else f"UPDATE {table} SET public_content='{{}}'::jsonb"
        )
    )
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db)
        connection.execute(text(statement))


@pytest.mark.parametrize("failure_at", ["outbox", "projection"])
def test_approval_and_selection_rollback_atomically(security_database, failure_at):
    db = security_database
    author, reviewer, coordinator = prepare(db)
    row = submit(db, author, create(db, author))
    engine = db.client.app.state.database.engine
    target = "INSERT INTO outbox_deliveries" if failure_at == "outbox" else "INSERT INTO question_selections"

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith(target):
            raise SQLAlchemyError("Injected failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = decide(db, reviewer, row, "approve")
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503
    current = db.client.get(review_path(db, row), headers=author).json()
    assert current["state"] == "in_review" and current["review_revision"] == 1
    assert db.client.get(path(db, "question-selections"), headers=coordinator).json() == []
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM audit_records WHERE action='question.review_approved'")
            )
            == 0
        )


def test_database_guard_rejects_forged_approval_and_missing_projection(security_database):
    db = security_database
    author, reviewer, _ = prepare(db)
    row = submit(db, author, create(db, author))

    def values(actor):
        return dict(
            id=uuid4(),
            tenant_id=db.ids["tenant_a"],
            question_id=UUID(row["question_id"]),
            version_id=UUID(row["version_id"]),
            content_hash=row["content_hash"],
            originating_author=db.ids["admin_a"],
            actor_user_id=db.ids[actor],
            sequence=2,
            expected_revision=1,
            action="approve",
            state="approved",
            reason=None,
        )

    # First is self-review; second is independent but omits the mandatory selection row.
    for actor in ["admin_a", "outsider"]:
        with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
            context(connection, db, actor)
            connection.execute(QuestionReviewEvent.__table__.insert().values(**values(actor)))


def test_review_audit_events_can_be_consumed_without_private_question_grants(outbox_database):
    db = outbox_database
    author, reviewer, _ = prepare(db)
    row = approve(db, reviewer, submit(db, author, create(db, author)))
    assert decide(db, reviewer, row, "retire", "Remove from future exams").status_code == 200
    result = db.worker.run_once(100)
    assert result.get("delivered") == 7  # three logins, create, submit, approve, retire
    assert db.worker.run_once(100) == {}
    for table in ["question_review_events", "question_selections"]:
        with pytest.raises(DBAPIError), db.worker_database.engine.begin() as connection:
            connection.execute(text("SELECT * FROM " + table))


def test_database_projection_strips_private_fields_even_if_service_passes_them(
    security_database, monkeypatch
):
    from app.question_bank import review

    db = security_database
    author, reviewer, coordinator = prepare(db)
    row = submit(db, author, create(db, author, EXAMPLES[6]))
    monkeypatch.setattr(review, "candidate_view", lambda content: content.model_dump(mode="json"))
    approved = approve(db, reviewer, row)
    selected = db.client.get(
        path(db, "question-selections", "/" + approved["version_id"]), headers=coordinator
    )
    assert selected.json()["content"] == candidate_view(validate_content(approved["content"]))
    assert "correct_option_id" not in json.dumps(selected.json())


def test_database_rejects_approval_without_submission_even_with_projection(security_database):
    db = security_database
    author, _, _ = prepare(db, "admin")
    row = create(db, author)
    decision_id = uuid4()
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db, "outsider")
        connection.execute(
            QuestionReviewEvent.__table__.insert().values(
                id=decision_id,
                tenant_id=db.ids["tenant_a"],
                question_id=UUID(row["question_id"]),
                version_id=UUID(row["version_id"]),
                content_hash=row["content_hash"],
                originating_author=db.ids["admin_a"],
                actor_user_id=db.ids["outsider"],
                sequence=1,
                expected_revision=1,
                action="approve",
                state="approved",
                reason=None,
            )
        )
        connection.execute(
            QuestionSelection.__table__.insert().values(
                version_id=UUID(row["version_id"]),
                tenant_id=db.ids["tenant_a"],
                question_id=UUID(row["question_id"]),
                title=row["title"],
                public_content={},
                state="approved",
                last_event_id=decision_id,
            )
        )


def test_upgrade_preserves_populated_v4_drafts_without_fabricated_approval(test_database):
    from app.db.models import Institution, Question, User
    from app.question_bank.contracts import content_hash

    _, engine, _, migrate = test_database
    migrate("0004_question_versions")
    tenant, user, question_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
    content = validate_content(EXAMPLES[0])
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)})
        connection.execute(text("SELECT set_config('app.actor_user_id', :actor, true)"), {"actor": str(user)})
        connection.execute(
            Institution.__table__.insert().values(id=tenant, slug="review-upgrade", name="Upgrade fixture")
        )
        connection.execute(
            User.__table__.insert().values(
                id=user, email="upgrade@example.test", display_name="Upgrade fixture"
            )
        )
        connection.execute(
            Membership.__table__.insert().values(id=uuid4(), tenant_id=tenant, user_id=user, role="admin")
        )
        connection.execute(
            Question.__table__.insert().values(id=question_id, tenant_id=tenant, created_by=user, revision=1)
        )
        connection.execute(
            QuestionVersion.__table__.insert().values(
                id=version_id,
                tenant_id=tenant,
                question_id=question_id,
                version_number=1,
                title="Preserved",
                schema_version="question-content.v1",
                content=content.model_dump(mode="json"),
                content_hash=content_hash(content),
                authored_by=user,
            )
        )
    migrate()
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)})
        connection.execute(text("SELECT set_config('app.actor_user_id', :actor, true)"), {"actor": str(user)})
        assert connection.scalar(
            select(QuestionVersion.content).where(QuestionVersion.id == version_id)
        ) == content.model_dump(mode="json")
        assert connection.scalar(text("SELECT count(*) FROM question_review_events")) == 0
        assert connection.scalar(text("SELECT count(*) FROM question_selections")) == 0
