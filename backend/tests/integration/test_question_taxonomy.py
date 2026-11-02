"""QBK-01/TEN-01/GOV-01 taxonomy and role-scoped retrieval on real PostgreSQL."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.db.models import Membership, QuestionVersionTaxon

pytestmark = pytest.mark.integration
CONTENT = json.loads(
    (Path(__file__).resolve().parents[3] / "docs/QUESTION_CONTENT_EXAMPLES.json").read_text()
)[0]


def path(db, kind="taxonomy", suffix="", tenant="a"):
    return f"/api/v1/tenants/{db.ids['tenant_' + tenant]}/{kind}" + suffix


def context(connection, db, actor="admin_a", tenant="a"):
    for setting, value in [("tenant_id", db.ids["tenant_" + tenant]), ("actor_user_id", db.ids[actor])]:
        connection.execute(text(f"SELECT set_config('app.{setting}', :value, true)"), {"value": str(value)})


def prepare(db):
    with db.admin_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            Membership.__table__.insert().values(
                id=uuid4(), tenant_id=db.ids["tenant_a"], user_id=db.ids["outsider"], role="reviewer"
            )
        )
        connection.execute(
            update(Membership)
            .where(Membership.id == db.ids["membership_candidate"])
            .values(role="coordinator")
        )
    return db.login("admin_a"), db.login("outsider"), db.login("candidate")


def term(db, who, kind="tag", code="sample", label="Original label", parent=None):
    body = {"kind": kind, "code": code, "label": label}
    if parent:
        body["parent_id"] = parent["id"]
    response = db.client.post(path(db), headers=who, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def create(db, who, ids=(), title="Taxonomy fixture", content=None):
    response = db.client.post(
        path(db, "questions"),
        headers=who,
        json={"title": title, "content": content or CONTENT, "taxonomy_ids": list(ids)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def change(db, who, item, **changes):
    return db.client.patch(
        path(db, suffix="/" + item["id"]),
        headers=who,
        json={"expected_revision": item["revision"], **changes},
    )


def decide(db, who, row, action, reason=None):
    body = {
        "action": action,
        "expected_revision": row["revision"],
        "expected_review_revision": row["review_revision"],
        "content_hash": row["content_hash"],
    }
    if reason:
        body["reason"] = reason
    response = db.client.post(
        path(db, "question-reviews", f"/{row['question_id']}/versions/{row['version_id']}"),
        headers=who,
        json=body,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_catalogue_snapshots_survive_rename_retirement_and_new_revision(security_database):
    db = security_database
    admin, reviewer, coordinator = prepare(db)
    subject = term(db, admin, "subject", "math", "Mathematics")
    topic = term(db, admin, "topic", "algebra", "Algebra", subject)
    outcome = term(db, admin, "outcome", "solve", "Solve equations")
    row = create(db, admin, [topic["id"], outcome["id"]])
    assert {x["id"] for x in row["taxonomy"]} == {subject["id"], topic["id"], outcome["id"]}
    frozen = row["taxonomy"]
    row = decide(db, reviewer, decide(db, admin, row, "submit"), "approve")
    assert change(db, admin, subject, state="retired").status_code == 409
    renamed = change(db, admin, topic, label="New topic label")
    assert renamed.status_code == 200
    assert change(db, admin, topic, label="Stale").status_code == 409
    assert change(db, admin, renamed.json(), state="retired").status_code == 200
    assert change(db, admin, subject, state="retired").status_code == 200
    old = db.client.get(path(db, "questions", "/" + row["question_id"]), headers=admin).json()
    assert old["taxonomy"] == frozen
    selected = db.client.get(path(db, "question-selections"), headers=coordinator).json()[0]
    assert selected["taxonomy"] == frozen and "content_hash" not in selected
    filtered = db.client.get(
        path(db, "question-selections"), headers=coordinator, params={"taxonomy_ids": topic["id"]}
    )
    assert filtered.status_code == 200 and filtered.json() == [selected]
    rejected = db.client.post(
        path(db, "questions"),
        headers=admin,
        json={"title": "Retired", "content": CONTENT, "taxonomy_ids": [topic["id"]]},
    )
    assert rejected.status_code == 404
    revision = db.client.post(
        path(db, "questions", f"/{row['question_id']}/versions"),
        headers=admin,
        json={"expected_revision": 1, "title": row["title"], "content": CONTENT},
    )
    assert (
        revision.status_code == 201
        and revision.json()["taxonomy"] == []
        and revision.json()["state"] == "draft"
    )
    assert revision.json()["content_hash"] == row["content_hash"]
    assert db.client.get(path(db, "question-selections"), headers=coordinator).json() == [selected]


@pytest.mark.parametrize("role", ["candidate", "invigilator", "examiner"])
def test_non_catalogue_roles_denied(security_database, role):
    db = security_database
    admin = db.login("admin_a")
    item = term(db, admin)
    with db.admin_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            update(Membership).where(Membership.id == db.ids["membership_candidate"]).values(role=role)
        )
    who = db.login("candidate")
    assert db.client.get(path(db), headers=who).status_code == 403
    assert db.client.get(path(db, suffix="/" + item["id"]), headers=who).status_code == 403
    assert change(db, who, item, label="Denied").status_code == 403


@pytest.mark.parametrize("role", ["author", "reviewer", "coordinator"])
def test_staff_catalogue_read_does_not_grant_mutation(security_database, role):
    db = security_database
    admin = db.login("admin_a")
    item = term(db, admin)
    with db.admin_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            update(Membership).where(Membership.id == db.ids["membership_candidate"]).values(role=role)
        )
    who = db.login("candidate")
    assert db.client.get(path(db), headers=who).status_code == 200
    assert change(db, who, item, label="Denied").status_code == 403
    assert (
        db.client.post(
            path(db), headers=who, json={"kind": "tag", "code": "other", "label": "Other"}
        ).status_code
        == 403
    )


def test_foreign_missing_and_retired_references_are_indistinguishable(security_database):
    db = security_database
    admin = db.login("admin_a")
    other = db.login("admin_b")
    foreign = db.client.post(
        path(db, tenant="b"), headers=other, json={"kind": "subject", "code": "foreign", "label": "Foreign"}
    ).json()
    item = term(db, admin)
    assert change(db, admin, item, state="retired").status_code == 200
    for identifier in [foreign["id"], str(uuid4()), item["id"]]:
        response = db.client.post(
            path(db, "questions"),
            headers=admin,
            json={"title": "Denied", "content": CONTENT, "taxonomy_ids": [identifier]},
        )
        assert response.status_code == 404 and response.json()["code"] == "taxonomy_not_found"
    for identifier in [foreign["id"], str(uuid4())]:
        response = db.client.get(path(db, "questions"), headers=admin, params={"taxonomy_ids": identifier})
        assert response.status_code == 404 and response.json()["code"] == "taxonomy_not_found"
    assert db.client.get(path(db, tenant="b"), headers=admin).status_code == 404
    assert (
        db.client.post(
            path(db),
            headers=admin,
            json={"kind": "topic", "code": "wrong", "label": "Wrong", "parent_id": foreign["id"]},
        ).status_code
        == 404
    )


def test_duplicate_codes_are_scoped_to_kind_and_institution(security_database):
    db = security_database
    admin = db.login("admin_a")
    term(db, admin)
    assert (
        db.client.post(
            path(db), headers=admin, json={"kind": "tag", "code": "sample", "label": "Duplicate"}
        ).status_code
        == 409
    )
    term(db, admin, "outcome")
    other = db.login("admin_b")
    assert (
        db.client.post(
            path(db, tenant="b"),
            headers=other,
            json={"kind": "tag", "code": "sample", "label": "Other institution"},
        ).status_code
        == 201
    )
    wrong = term(db, admin, "tag", "wrong")
    assert (
        db.client.post(
            path(db),
            headers=admin,
            json={"kind": "topic", "code": "topic", "label": "Wrong parent", "parent_id": wrong["id"]},
        ).status_code
        == 409
    )


def test_title_search_is_literal_and_filtering_precedes_stable_pagination(security_database):
    db = security_database
    admin, reviewer, coordinator = prepare(db)
    first = term(db, admin, code="first")
    second = term(db, admin, code="second")
    rows = [create(db, admin, [first["id"], second["id"]], title="Literal 50%_ / marker") for _ in range(3)]
    create(db, admin, [first["id"]], title="Literal 50XX / marker")
    create(db, admin, [first["id"], second["id"]], title="Different")
    params = [
        ("q", "50%_ /"),
        ("kind", "single_choice"),
        ("state", "draft"),
        ("taxonomy_ids", first["id"]),
        ("taxonomy_ids", second["id"]),
        ("limit", "1"),
    ]
    pages = [
        db.client.get(path(db, "questions"), headers=admin, params=[*params, ("offset", str(n))])
        for n in range(4)
    ]
    assert all(p.status_code == 200 for p in pages)
    assert len({p.json()[0]["version_id"] for p in pages[:3]}) == 3 and pages[3].json() == []
    assert {p.json()[0]["version_id"] for p in pages[:3]} == {r["version_id"] for r in rows}
    submitted = decide(db, admin, rows[0], "submit")
    query = {"taxonomy_ids": first["id"], "state": "in_review", "q": "50%_"}
    assert [
        r["version_id"]
        for r in db.client.get(path(db, "question-reviews"), headers=reviewer, params=query).json()
    ] == [submitted["version_id"]]
    approved = decide(db, reviewer, submitted, "approve")
    assert (
        db.client.get(
            path(db, "question-selections"), headers=coordinator, params={"state": "draft"}
        ).status_code
        == 422
    )
    selected = db.client.get(
        path(db, "question-selections"),
        headers=coordinator,
        params={"q": "50%_", "taxonomy_ids": second["id"], "kind": "single_choice"},
    ).json()
    assert len(selected) == 1 and selected[0]["version_id"] == approved["version_id"]
    with db.runtime_engine.begin() as connection:
        context(connection, db, "candidate")
        assert connection.scalar(text("SELECT count(*) FROM question_versions")) == 0
        assert connection.scalar(text("SELECT count(*) FROM question_version_taxa")) == 2
    decide(db, reviewer, approved, "retire", "Stop selecting")
    with db.runtime_engine.begin() as connection:
        context(connection, db, "candidate")
        assert connection.scalar(text("SELECT count(*) FROM question_version_taxa")) == 0


def test_classification_cannot_be_attached_after_version_creation(security_database):
    db = security_database
    admin = db.login("admin_a")
    item = term(db, admin)
    row = create(db, admin)
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            QuestionVersionTaxon.__table__.insert().values(
                tenant_id=db.ids["tenant_a"],
                question_id=UUID(row["question_id"]),
                version_id=UUID(row["version_id"]),
                term_id=UUID(item["id"]),
                kind_snapshot="tag",
                code_snapshot="forged",
                label_snapshot="Forged",
                parent_id_snapshot=None,
                term_revision=1,
            )
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE taxonomy_terms SET code='changed'",
        "DELETE FROM taxonomy_terms",
        "TRUNCATE taxonomy_terms",
        "UPDATE question_version_taxa SET label_snapshot='changed'",
        "DELETE FROM question_version_taxa",
        "TRUNCATE question_version_taxa",
    ],
)
def test_runtime_cannot_rewrite_catalogue_identity_or_classification(security_database, statement):
    db = security_database
    admin = db.login("admin_a")
    item = term(db, admin)
    create(db, admin, [item["id"]])
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db)
        connection.execute(text(statement))


@pytest.mark.parametrize("operation", ["create_term", "change_term", "save_question"])
def test_taxonomy_and_version_changes_rollback_with_outbox_failure(security_database, operation):
    db = security_database
    admin = db.login("admin_a")
    item = term(db, admin)
    engine = db.client.app.state.database.engine

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith("INSERT INTO outbox_deliveries"):
            raise SQLAlchemyError("Injected failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        if operation == "create_term":
            response = db.client.post(
                path(db), headers=admin, json={"kind": "tag", "code": "rolled_back", "label": "Private label"}
            )
        elif operation == "change_term":
            response = change(db, admin, item, label="Private label")
        else:
            response = db.client.post(
                path(db, "questions"),
                headers=admin,
                json={"title": "Rolled back", "content": CONTENT, "taxonomy_ids": [item["id"]]},
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(text("SELECT count(*) FROM taxonomy_terms")) == 1
        assert connection.scalar(text("SELECT revision FROM taxonomy_terms")) == 1
        assert connection.scalar(text("SELECT count(*) FROM question_version_taxa")) == 0
        assert connection.scalar(text("SELECT count(*) FROM questions")) == 0
        assert (
            connection.scalar(text("SELECT count(*) FROM audit_records WHERE action='taxonomy.changed'")) == 0
        )


def test_concurrent_catalogue_updates_have_one_winner(security_database):
    db = security_database
    admin = db.login("admin_a")
    item = term(db, admin)
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(
            executor.map(lambda label: change(db, admin, item, label=label).status_code, ["One", "Two"])
        )
    assert sorted(statuses) == [200, 409]


def test_worker_has_no_taxonomy_or_classification_grants(outbox_database):
    db = outbox_database
    admin = db.login("admin_a")
    item = term(db, admin)
    create(db, admin, [item["id"]])
    assert db.worker.run_once(100).get("delivered") == 3
    for table in ["taxonomy_terms", "question_version_taxa"]:
        with pytest.raises(DBAPIError), db.worker_database.engine.begin() as connection:
            connection.execute(text("SELECT * FROM " + table))


def test_audit_contains_ids_and_counters_not_labels(security_database):
    db = security_database
    admin = db.login("admin_a")
    item = term(db, admin, label="Secret catalogue text")
    assert change(db, admin, item, label="Other private catalogue text").status_code == 200
    with db.admin_engine.begin() as connection:
        context(connection, db)
        payload = (
            connection.execute(
                text(
                    "SELECT before_state::text || after_state::text FROM audit_records WHERE action LIKE 'taxonomy.%' ORDER BY created_at"
                )
            )
            .scalars()
            .all()
        )
    assert len(payload) == 2 and "catalogue text" not in "".join(payload)


def test_database_derives_snapshot_fields_instead_of_trusting_service(security_database):
    db = security_database
    admin = db.login("admin_a")
    item = term(db, admin)

    def tamper(mapper, connection, target):
        target.label_snapshot = "Forged label"
        target.code_snapshot = "forged"
        target.term_revision = 999

    event.listen(QuestionVersionTaxon, "before_insert", tamper)
    try:
        row = create(db, admin, [item["id"]])
    finally:
        event.remove(QuestionVersionTaxon, "before_insert", tamper)
    assert row["taxonomy"][0]["label"] == item["label"]
    assert row["taxonomy"][0]["code"] == item["code"] and row["taxonomy"][0]["revision"] == 1


def test_populated_v5_upgrade_preserves_unclassified_version(test_database):
    from app.db.models import Institution, Question, QuestionVersion, User
    from app.question_bank.contracts import content_hash, validate_content

    _, engine, _, migrate = test_database
    migrate("0005_question_review")
    tenant, user, question, version = uuid4(), uuid4(), uuid4(), uuid4()
    content = validate_content(CONTENT)
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id',:id,true)"), {"id": str(tenant)})
        connection.execute(text("SELECT set_config('app.actor_user_id',:id,true)"), {"id": str(user)})
        connection.execute(
            Institution.__table__.insert().values(id=tenant, slug="taxonomy-upgrade", name="Upgrade")
        )
        connection.execute(
            User.__table__.insert().values(id=user, email="taxonomy@example.test", display_name="Upgrade")
        )
        connection.execute(
            Membership.__table__.insert().values(id=uuid4(), tenant_id=tenant, user_id=user, role="admin")
        )
        connection.execute(
            Question.__table__.insert().values(id=question, tenant_id=tenant, created_by=user, revision=1)
        )
        connection.execute(
            QuestionVersion.__table__.insert().values(
                id=version,
                tenant_id=tenant,
                question_id=question,
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
        connection.execute(text("SELECT set_config('app.tenant_id',:id,true)"), {"id": str(tenant)})
        connection.execute(text("SELECT set_config('app.actor_user_id',:id,true)"), {"id": str(user)})
        assert connection.scalar(
            select(QuestionVersion.content).where(QuestionVersion.id == version)
        ) == content.model_dump(mode="json")
        assert (
            connection.scalar(select(QuestionVersion.created_txid).where(QuestionVersion.id == version)) == 0
        )
        assert connection.scalar(text("SELECT count(*) FROM question_version_taxa")) == 0


@pytest.mark.parametrize("revocation,status", [("role", 403), ("session", 401)])
def test_catalogue_authority_is_rechecked_after_waiting_for_lock(security_database, revocation, status):
    from threading import Event

    from app.db.models import AuthSession

    db = security_database
    admin = db.login("admin_a")
    item = term(db, admin)
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
                pending = executor.submit(change, db, admin, item, label="Revoked")
                assert reached.wait(3)
                if revocation == "role":
                    connection.execute(
                        update(Membership)
                        .where(Membership.id == db.ids["membership_a"])
                        .values(role="author")
                    )
                else:
                    connection.execute(
                        update(AuthSession)
                        .where(AuthSession.user_id == db.ids["admin_a"])
                        .values(revoked_at=text("clock_timestamp()"))
                    )
            assert pending.result(timeout=8).status_code == status
    finally:
        event.remove(engine, "before_cursor_execute", observe)
