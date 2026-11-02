"""QBK-01/TEN-01/PUB-01/IAM-01/GOV-01 against real restricted PostgreSQL accounts."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.db.models import AuditRecord, AuthSession, Institution, Membership, OutboxEvent, Question, User

pytestmark = pytest.mark.integration
EXAMPLES = json.loads(
    (Path(__file__).resolve().parents[3] / "docs/QUESTION_CONTENT_EXAMPLES.json").read_text()
)


def path(db, suffix="", tenant="a"):
    return f"/api/v1/tenants/{db.ids['tenant_' + tenant]}/questions" + suffix


def context(connection, db, tenant="a", actor="admin_a"):
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(db.ids["tenant_" + tenant])}
    )
    connection.execute(
        text("SELECT set_config('app.actor_user_id', :actor, true)"), {"actor": str(db.ids[actor])}
    )


def create(db, headers, content=None, tenant="a"):
    response = db.client.post(
        path(db, tenant=tenant),
        headers=headers,
        json={"title": "Saved question", "content": content or EXAMPLES[0]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def revise(db, headers, row, revision=None, content=None):
    return db.client.post(
        path(db, f"/{row['question_id']}/versions"),
        headers=headers,
        json={
            "expected_revision": revision or row["revision"],
            "title": "Revised question",
            "content": content or EXAMPLES[1],
        },
    )


def assign(db, user, role):
    with db.admin_engine.begin() as connection:
        context(connection, db)
        if user == "candidate":
            connection.execute(
                update(Membership).where(Membership.id == db.ids["membership_candidate"]).values(role=role)
            )
        else:
            connection.execute(
                Membership.__table__.insert().values(
                    id=uuid4(), tenant_id=db.ids["tenant_a"], user_id=db.ids[user], role=role
                )
            )


@pytest.mark.parametrize("content", EXAMPLES, ids=[item["kind"] for item in EXAMPLES])
def test_each_type_persists_with_private_staff_detail_and_safe_preview(security_database, content):
    db = security_database
    headers = db.login("admin_a")
    row = create(db, headers, content)
    assert row["revision"] == row["version_number"] == 1
    assert row["state"] == "draft"
    assert db.client.get(path(db, "/" + row["question_id"]), headers=headers).json() == row
    preview = db.client.get(path(db, "/" + row["question_id"] + "/preview"), headers=headers)
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    assert "content_hash" not in preview.json()
    private = {
        "correct_option_id",
        "correct_option_ids",
        "expected",
        "absolute_tolerance",
        "accepted_answers",
        "normalization",
        "marker_guidance",
        "rubric",
        "scoring",
    }

    def inspect(value):
        if isinstance(value, dict):
            assert not private.intersection(value)
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(preview.json())


def test_revision_preserves_content_title_author_and_old_version_projection(security_database):
    db = security_database
    headers = db.login("admin_a")
    first = create(db, headers)
    response = revise(db, headers, first)
    assert response.status_code == 201, response.text
    second = response.json()
    assert second["revision"] == second["version_number"] == 2
    assert first["version_id"] != second["version_id"]
    old = db.client.get(
        path(db, f"/{first['question_id']}/versions/{first['version_id']}"), headers=headers
    ).json()
    assert old["content"] == first["content"] and old["title"] == first["title"]
    assert old["content_hash"] == first["content_hash"]
    assert old["version_number"] == 1 and old["revision"] == 2
    history = db.client.get(path(db, f"/{first['question_id']}/versions"), headers=headers).json()
    assert [row["version_number"] for row in history] == [2, 1]
    assert all("content" not in row for row in history)
    old_preview = db.client.get(
        path(db, f"/{first['question_id']}/preview?version_id={first['version_id']}"), headers=headers
    )
    assert old_preview.json()["content"]["kind"] == "single_choice"


def test_stale_save_is_a_controlled_conflict_without_extra_version_or_audit(security_database):
    db = security_database
    headers = db.login("admin_a")
    first = create(db, headers)
    assert revise(db, headers, first).status_code == 201
    response = revise(db, headers, first)
    assert response.status_code == 409
    assert response.json()["code"] == "question_conflict"
    assert response.headers["x-request-id"] == response.json()["request_id"]
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(text("SELECT count(*) FROM question_versions")) == 2
        assert (
            connection.scalar(text("SELECT count(*) FROM audit_records WHERE action = 'question.revised'"))
            == 1
        )


def test_concurrent_saves_have_one_winner_and_unique_versions(security_database):
    db = security_database
    headers = db.login("admin_a")
    row = create(db, headers)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: revise(db, headers, row), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert [
        r["version_number"]
        for r in db.client.get(path(db, f"/{row['question_id']}/versions"), headers=headers).json()
    ] == [2, 1]


@pytest.mark.parametrize("role", ["candidate", "coordinator", "reviewer", "examiner", "invigilator"])
def test_non_authoring_roles_cannot_access_saved_drafts_or_preview(security_database, role):
    db = security_database
    admin = db.login("admin_a")
    row = create(db, admin)
    assign(db, "candidate", role)
    headers = db.login("candidate")
    for suffix in [
        "",
        "/" + row["question_id"],
        f"/{row['question_id']}/versions",
        f"/{row['question_id']}/versions/{row['version_id']}",
        f"/{row['question_id']}/preview",
    ]:
        assert db.client.get(path(db, suffix), headers=headers).status_code == 403
    assert (
        db.client.post(
            path(db), headers=headers, json={"title": "Denied", "content": EXAMPLES[0]}
        ).status_code
        == 403
    )
    assert revise(db, headers, row).status_code == 403


def test_authors_only_see_and_revise_their_own_question_identities(security_database):
    db = security_database
    assign(db, "candidate", "author")
    assign(db, "outsider", "author")
    first, second, admin = db.login("candidate"), db.login("outsider"), db.login("admin_a")
    row = create(db, first)
    other = create(db, second)
    assert {r["question_id"] for r in db.client.get(path(db), headers=first).json()} == {row["question_id"]}
    assert db.client.get(path(db, "/" + other["question_id"]), headers=first).status_code == 404
    assert revise(db, first, other).status_code == 404
    assert db.client.get(path(db, f"/{other['question_id']}/preview"), headers=first).status_code == 404
    # Admin may edit but the originating author cannot be erased.
    amended = revise(db, admin, row).json()
    assert amended["created_by"] == str(db.ids["candidate"])
    assert amended["authored_by"] == str(db.ids["admin_a"])
    assert db.client.get(path(db, "/" + row["question_id"]), headers=first).status_code == 200


def test_foreign_tenants_versions_and_random_identifiers_are_not_disclosed(security_database):
    db = security_database
    a, b = db.login("admin_a"), db.login("admin_b")
    first, second = create(db, a), create(db, b, tenant="b")
    for identifier in [second["question_id"], str(uuid4())]:
        assert db.client.get(path(db, "/" + identifier), headers=a).status_code == 404
        assert revise(db, a, {**first, "question_id": identifier}).status_code == 404
    assert db.client.get(path(db, tenant="b"), headers=a).status_code == 404
    for identifier in [second["version_id"], str(uuid4())]:
        assert (
            db.client.get(path(db, f"/{first['question_id']}/versions/{identifier}"), headers=a).status_code
            == 404
        )
        assert (
            db.client.get(
                path(db, f"/{first['question_id']}/preview?version_id={identifier}"), headers=a
            ).status_code
            == 404
        )
    assert {r["question_id"] for r in db.client.get(path(db), headers=a).json()} == {first["question_id"]}


def test_malformed_content_mass_assignment_and_pagination_rejected(security_database):
    db = security_database
    headers = db.login("admin_a")
    invalid = copy.deepcopy(EXAMPLES[0])
    invalid["correct_option_id"] = "missing"
    for payload in [
        {"title": "Bad", "content": invalid},
        {"title": "Bad", "content": EXAMPLES[0], "tenant_id": str(db.ids["tenant_b"])},
        {"title": "Bad", "content": EXAMPLES[0], "state": "approved"},
    ]:
        response = db.client.post(path(db), headers=headers, json=payload)
        assert response.status_code == 422
        assert "First option" not in response.text
    for suffix in ["?limit=0", "?limit=201", "?offset=-1"]:
        assert db.client.get(path(db, suffix), headers=headers).status_code == 422
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(text("SELECT count(*) FROM questions")) == 0


def test_revision_without_snapshot_and_skipping_revision_fail_at_database(security_database):
    db = security_database
    row = create(db, db.login("admin_a"))
    for increment in [1, 2]:
        with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
            context(connection, db)
            connection.execute(
                text("UPDATE questions SET revision = revision + :increment WHERE id=:id"),
                {"increment": increment, "id": UUID(row["question_id"])},
            )
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(select(Question.revision)) == 1


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE question_versions SET title = 'tampered'",
        "UPDATE question_versions SET content = '{}'::jsonb",
        "DELETE FROM question_versions",
        "DELETE FROM questions",
        "TRUNCATE questions, question_versions",
        "UPDATE questions SET created_by = created_by",
        "ALTER TABLE question_versions DISABLE ROW LEVEL SECURITY",
    ],
)
def test_restricted_runtime_cannot_rewrite_or_remove_history(security_database, statement):
    db = security_database
    create(db, db.login("admin_a"))
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db)
        connection.execute(text(statement))


def test_immutable_guard_still_denies_owner_update_and_delete(security_database):
    db = security_database
    create(db, db.login("admin_a"))
    # Deliberately relax RLS only in this disposable test DB to exercise the trigger itself.
    with db.admin_engine.begin() as connection:
        connection.execute(text("CREATE POLICY fixture_update ON question_versions FOR UPDATE USING (true)"))
        connection.execute(text("CREATE POLICY fixture_delete ON question_versions FOR DELETE USING (true)"))
    for statement in ["UPDATE question_versions SET title='tampered'", "DELETE FROM question_versions"]:
        with pytest.raises(DBAPIError), db.admin_engine.begin() as connection:
            context(connection, db)
            connection.execute(text(statement))


def test_rls_hides_rows_without_context_wrong_tenant_or_wrong_author(security_database):
    db = security_database
    row = create(db, db.login("admin_a"))
    with db.runtime_engine.connect() as connection:
        for table in ["questions", "question_versions"]:
            assert connection.scalar(text("SELECT count(*) FROM " + table)) == 0
        connection.rollback()
        with connection.begin():
            context(connection, db, "b", "admin_b")
            assert connection.scalar(text("SELECT count(*) FROM questions")) == 0
            assert connection.scalar(text("SELECT count(*) FROM question_versions")) == 0
            assert (
                connection.execute(
                    text("UPDATE questions SET revision=revision+1 WHERE id=:id"),
                    {"id": UUID(row["question_id"])},
                ).rowcount
                == 0
            )
        assert connection.scalar(text("SELECT count(*) FROM questions")) == 0
    assign(db, "candidate", "author")
    with db.runtime_engine.begin() as connection:
        context(connection, db, actor="candidate")
        assert connection.scalar(text("SELECT count(*) FROM questions")) == 0
        assert connection.scalar(text("SELECT count(*) FROM question_versions")) == 0


def test_cross_tenant_append_cannot_reference_another_tenants_question(security_database):
    db = security_database
    row = create(db, db.login("admin_a"))
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db, "b", "admin_b")
        connection.execute(
            text("""INSERT INTO question_versions
            (id, tenant_id, question_id, version_number, title, schema_version, content, content_hash, authored_by)
            VALUES (:id, :tenant, :question, 1, 'Bad link', 'question-content.v1', '{}'::jsonb, :hash, :actor)"""),
            {
                "id": uuid4(),
                "tenant": db.ids["tenant_b"],
                "question": UUID(row["question_id"]),
                "hash": "a" * 64,
                "actor": db.ids["admin_b"],
            },
        )


@pytest.mark.parametrize("operation", ["create", "revise"])
def test_outbox_failure_rolls_back_question_snapshot_pointer_and_audit(
    security_database, monkeypatch, operation
):
    db = security_database
    headers = db.login("admin_a")
    row = create(db, headers) if operation == "revise" else None
    # Fail precisely at delivery insertion, after business and audit/event flushes.
    engine = db.client.app.state.database.engine

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith("INSERT INTO outbox_deliveries"):
            raise SQLAlchemyError("Injected delivery failure; no content included")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = (
            revise(db, headers, row)
            if row
            else db.client.post(path(db), headers=headers, json={"title": "Atomic", "content": EXAMPLES[0]})
        )
        assert response.status_code == 503
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(text("SELECT count(*) FROM questions")) == (1 if row else 0)
        assert connection.scalar(text("SELECT count(*) FROM question_versions")) == (1 if row else 0)
        assert connection.scalar(
            text("SELECT count(*) FROM audit_records WHERE action LIKE 'question.%'")
        ) == (1 if row else 0)
        assert connection.scalar(
            text("SELECT count(*) FROM outbox_events WHERE payload->>'action' LIKE 'question.%'")
        ) == (1 if row else 0)
        if row:
            assert connection.scalar(select(Question.revision)) == 1


def test_audit_records_only_allowlisted_version_metadata_and_worker_can_consume(outbox_database):
    db = outbox_database
    headers = db.login("admin_a")
    row = create(db, headers)
    assert revise(db, headers, row).status_code == 201
    with db.admin_engine.begin() as connection:
        context(connection, db)
        rows = (
            connection.execute(
                select(AuditRecord)
                .where(AuditRecord.action.like("question.%"))
                .order_by(AuditRecord.created_at, AuditRecord.id)
            )
            .mappings()
            .all()
        )
        assert len(rows) == 2
        for record in rows:
            for state in [record["before_state"], record["after_state"]]:
                assert set(state) <= {"version_id", "revision", "content_hash"}
            assert record["request_id"] is not None
        payloads = connection.execute(select(OutboxEvent.payload)).scalars().all()
        assert "First option" not in json.dumps(payloads)
        assert "correct_option_id" not in json.dumps(payloads)
    assert db.worker.run_once(100).get("delivered") == 3  # login, create, revise
    assert db.worker.run_once(100) == {}
    with pytest.raises(DBAPIError), db.worker_database.engine.begin() as connection:
        connection.execute(text("SELECT content FROM question_versions"))


@pytest.mark.parametrize("revocation,expected_status", [("role", 403), ("session", 401)])
def test_authority_is_rechecked_after_waiting_for_mutation_lock(
    security_database, revocation, expected_status
):
    db = security_database
    assign(db, "candidate", "author")
    headers = db.login("candidate")
    row = create(db, headers)
    reached = Event()
    engine = db.client.app.state.database.engine

    def waiting(connection, cursor, statement, parameters, ctx, executemany):
        if "FROM institutions" in statement and "FOR UPDATE" in statement:
            reached.set()

    event.listen(engine, "before_cursor_execute", waiting)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with db.admin_engine.begin() as connection:
                context(connection, db)
                connection.execute(select(Membership.id).limit(1))
                connection.execute(
                    text("SELECT id FROM institutions WHERE id=:id FOR UPDATE"), {"id": db.ids["tenant_a"]}
                )
                future = executor.submit(revise, db, headers, row)
                assert reached.wait(3), "writer did not reach institution lock"
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
            assert future.result(timeout=8).status_code == expected_status
    finally:
        event.remove(engine, "before_cursor_execute", waiting)
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(select(Question.revision)) == 1


def test_upgrade_from_populated_p1_preserves_existing_records(test_database):
    _, engine, _, migrate = test_database
    migrate("0003_audit_outbox")
    tenant, user = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)})
        connection.execute(
            Institution.__table__.insert().values(id=tenant, slug="preserved-institute", name="Preserved")
        )
        connection.execute(
            User.__table__.insert().values(id=user, email="preserved@example.test", display_name="Preserved")
        )
        connection.execute(
            Membership.__table__.insert().values(id=uuid4(), tenant_id=tenant, user_id=user, role="author")
        )
    migrate()
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)})
        assert connection.scalar(select(Institution.name).where(Institution.id == tenant)) == "Preserved"
        assert connection.scalar(select(User.email).where(User.id == user)) == "preserved@example.test"
        assert connection.scalar(select(Membership.role).where(Membership.user_id == user)) == "author"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0004_question_versions"


def test_readiness_requires_new_runtime_grants(security_database):
    import psycopg
    from psycopg import sql
    from sqlalchemy.engine import make_url

    db = security_database
    role = make_url(db.runtime_url).username
    # Use psycopg identifiers, not string interpolation of a role name.
    parsed = db.admin_engine.url.set(drivername="postgresql")
    with psycopg.connect(parsed.render_as_string(hide_password=False)) as connection:
        connection.execute(sql.SQL("REVOKE INSERT ON questions FROM {}").format(sql.Identifier(role)))
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"]["runtime_role"] == "missing_grants"


def test_readiness_rejects_disabled_immutable_guard(security_database):
    db = security_database
    with db.admin_engine.begin() as connection:
        connection.execute(text("ALTER TABLE question_versions DISABLE TRIGGER question_version_guard"))
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"]["runtime_role"] == "unsafe"
