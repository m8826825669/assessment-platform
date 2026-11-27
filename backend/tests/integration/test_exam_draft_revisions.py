"""ASM-01/PUB-01/TEN-01/GOV-01 immutable draft edits and publication fencing."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from test_question_review import approve, context, create, path, prepare, submit

pytestmark = pytest.mark.integration


@pytest.fixture
def drafts(security_database):
    db = security_database
    author, reviewer, coordinator = prepare(db)
    draft_id = uuid4()
    url = path(db, "exam-blueprints", f"/drafts/{draft_id}")
    response = db.client.put(url, headers=coordinator, json={"sections": []})
    assert response.status_code == 200, response.text
    return db, author, reviewer, coordinator, url, response.json()


def edit(db, coordinator, url, *, revision=1, identity=None, sections=None):
    body = {
        "id": str(identity or uuid4()),
        "expected_revision": revision,
        "sections": sections if sections is not None else [],
    }
    return db.client.post(url + "/revisions", headers=coordinator, json=body)


def test_revision_history_replay_conflict_and_stale_editor(drafts):
    db, _, _, coordinator, url, first = drafts
    assert first["revision"] == 1 and first["exam_id"] == first["id"] and first["parent_id"] is None
    identity = uuid4()
    changed = [{"version_ids": [], "minimum": 0, "maximum": 0}]
    response = edit(db, coordinator, url, identity=identity, sections=changed)
    assert response.status_code == 200, response.text
    second = response.json()
    assert second["revision"] == 2 and second["exam_id"] == first["id"] and second["parent_id"] == first["id"]
    assert db.client.get(url, headers=coordinator).json() == first
    assert edit(db, coordinator, url, identity=identity, sections=changed).json() == second
    assert edit(db, coordinator, url, identity=identity).status_code == 409
    assert edit(db, coordinator, url).status_code == 409
    assert edit(db, coordinator, url, revision=2).status_code == 409
    child_url = path(db, "exam-blueprints", f"/drafts/{identity}")
    third = edit(db, coordinator, child_url, revision=2)
    assert third.status_code == 200, third.text
    assert third.json()["revision"] == 3
    assert edit(db, coordinator, url, identity=identity, sections=changed).json() == second
    history = db.client.get(url + "/history", headers=coordinator)
    assert history.status_code == 200
    assert history.json() == [first, second, third.json()]
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert (
            connection.scalar(text("SELECT count(*) FROM audit_records WHERE action='exam.draft_revised'"))
            == 2
        )


def test_competing_editors_produce_one_revision(drafts):
    db, _, _, coordinator, url, first = drafts
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: edit(db, coordinator, url), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(db.client.get(url + "/history", headers=coordinator).json()) == 2


def test_identical_concurrent_edit_retry_returns_one_revision(drafts):
    db, _, _, coordinator, url, first = drafts
    identity = uuid4()
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: edit(db, coordinator, url, identity=identity), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert len(db.client.get(url + "/history", headers=coordinator).json()) == 2


@pytest.mark.parametrize("table", ["audit_records", "outbox_events", "outbox_deliveries"])
def test_revision_rolls_back_on_transaction_failure(drafts, table):
    db, _, _, coordinator, url, first = drafts
    engine = db.client.app.state.database.engine
    identity = uuid4()

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith("INSERT INTO " + table):
            raise SQLAlchemyError("Injected draft revision failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = edit(db, coordinator, url, identity=identity)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503, response.text
    assert db.client.get(url + "/history", headers=coordinator).json() == [first]
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert (
            connection.scalar(text("SELECT count(*) FROM audit_records WHERE action='exam.draft_revised'"))
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM outbox_events WHERE payload->>'action'='exam.draft_revised'")
            )
            == 0
        )
    retry = edit(db, coordinator, url, identity=identity)
    assert retry.status_code == 200 and retry.json()["revision"] == 2


def test_revision_permissions_and_tenant_scope(drafts):
    db, _, reviewer, coordinator, url, first = drafts
    assert edit(db, reviewer, url).status_code == 403
    assert db.client.get(url + "/history", headers=reviewer).status_code == 403
    foreign = url.replace(str(db.ids["tenant_a"]), str(db.ids["tenant_b"]))
    assert edit(db, coordinator, foreign).status_code == 404
    assert db.client.get(foreign + "/history", headers=coordinator).status_code == 404
    assert edit(db, coordinator, url, identity=UUID(first["id"])).status_code == 409


@pytest.mark.parametrize("bad", [0, -1, True, "1", 2147483647])
def test_revision_rejects_invalid_counter(drafts, bad):
    db, _, _, coordinator, url, first = drafts
    assert edit(db, coordinator, url, revision=bad).status_code == 422
    assert db.client.get(url + "/history", headers=coordinator).json() == [first]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE exam_blueprint_drafts SET blueprint='{}'::jsonb WHERE id=:id",
        "DELETE FROM exam_blueprint_drafts WHERE id=:id",
    ],
)
def test_database_draft_guard_rejects_history_rewrite(drafts, statement):
    db, _, _, coordinator, url, first = drafts
    with pytest.raises(DBAPIError):
        with db.admin_engine.begin() as connection:
            connection.execute(text(statement), {"id": UUID(first["id"])})
    assert db.client.get(url, headers=coordinator).json() == first


def test_database_rejects_branch_from_stale_parent(drafts):
    db, _, _, coordinator, url, first = drafts
    assert edit(db, coordinator, url).status_code == 200
    with pytest.raises(DBAPIError):
        with db.runtime_engine.begin() as connection:
            context(connection, db, "candidate")
            connection.execute(
                text(
                    "INSERT INTO exam_blueprint_drafts(tenant_id,id,exam_id,revision,parent_id,blueprint) "
                    "VALUES(:tenant,:id,:root,3,:root,'{\"sections\":[]}'::jsonb)"
                ),
                {"tenant": db.ids["tenant_a"], "id": uuid4(), "root": UUID(first["id"])},
            )


def test_new_revision_fences_publication_but_preserves_existing_snapshot(drafts):
    db, author, reviewer, coordinator, url, first = drafts
    question = approve(db, reviewer, submit(db, author, create(db, author)))
    sections = [{"version_ids": [question["version_id"]], "minimum": 1, "maximum": 1}]
    second = edit(db, coordinator, url, sections=sections).json()
    child = path(db, "exam-blueprints", f"/drafts/{second['id']}")
    assert db.client.post(url + "/publish", headers=coordinator).status_code == 409
    assert db.client.post(child + "/publish?expected_revision=1", headers=coordinator).status_code == 409
    publication = db.client.post(child + "/publish?expected_revision=2", headers=coordinator)
    assert publication.status_code == 200, publication.text
    third = edit(db, coordinator, child, revision=2, sections=sections)
    assert third.status_code == 200, third.text
    assert (
        db.client.post(child + "/publish?expected_revision=2", headers=coordinator).json()
        == publication.json()
    )
    get_url = path(db, "exam-blueprints", f"/publications/{second['id']}")
    assert db.client.get(get_url, headers=coordinator).json() == publication.json()
    latest = path(db, "exam-blueprints", f"/drafts/{third.json()['id']}")
    assert db.client.post(latest + "/publish?expected_revision=3", headers=coordinator).status_code == 200


def test_readiness_detects_disabled_draft_guard(security_database):
    db = security_database
    with db.admin_engine.begin() as connection:
        connection.execute(text("ALTER TABLE exam_blueprint_drafts DISABLE TRIGGER exam_draft_guard"))
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"]["runtime_role"] == "unsafe"


def test_upgrade_preserves_legacy_draft_and_publication(test_database):
    _, engine, _, migrate = test_database
    migrate("0012_publication_access")
    tenant, identity = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO institutions(id,slug,name) VALUES(:id,:slug,'Legacy')"),
            {"id": tenant, "slug": "legacy-" + tenant.hex},
        )
        connection.execute(
            text(
                "INSERT INTO exam_blueprint_drafts(tenant_id,id,blueprint) "
                "VALUES(:tenant,:id,'{\"sections\":[]}'::jsonb)"
            ),
            {"tenant": tenant, "id": identity},
        )
        connection.execute(
            text(
                "INSERT INTO exam_publications(tenant_id,id,snapshot) "
                "VALUES(:tenant,:id,jsonb_build_object('schema_version', 1))"
            ),
            {"tenant": tenant, "id": identity},
        )
    migrate()
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT exam_id,revision,parent_id,blueprint FROM exam_blueprint_drafts WHERE id=:id"),
            {"id": identity},
        ).one()
        assert tuple(row) == (identity, 1, None, {"sections": []})
        assert connection.scalar(
            text("SELECT snapshot FROM exam_publications WHERE id=:id"), {"id": identity}
        ) == {"schema_version": 1}


@pytest.mark.parametrize("first_operation", ["publish", "edit"])
def test_publication_and_edit_follow_institution_lock_order(drafts, first_operation):
    db, author, reviewer, coordinator, root_url, first = drafts
    question = approve(db, reviewer, submit(db, author, create(db, author)))
    sections = [{"version_ids": [question["version_id"]], "minimum": 1, "maximum": 1}]
    second = edit(db, coordinator, root_url, sections=sections).json()
    url = path(db, "exam-blueprints", f"/drafts/{second['id']}")
    entered, release = Event(), Event()
    table = "exam_publications" if first_operation == "publish" else "exam_blueprint_drafts"
    engine = db.client.app.state.database.engine

    def hold(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith("INSERT INTO " + table) and not entered.is_set():
            entered.set()
            assert release.wait(15), "Test release timed out"

    def publish():
        return db.client.post(url + "/publish?expected_revision=2", headers=coordinator)

    def revise():
        return edit(db, coordinator, url, revision=2, sections=sections)

    event.listen(engine, "before_cursor_execute", hold)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(publish if first_operation == "publish" else revise)
            try:
                assert entered.wait(15), "First transaction did not reach its write"
                second_future = executor.submit(revise if first_operation == "publish" else publish)
            finally:
                release.set()
            first_response = first_future.result(timeout=30)
            second_response = second_future.result(timeout=30)
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", hold)
    published = first_response if first_operation == "publish" else second_response
    revised = second_response if first_operation == "publish" else first_response
    assert revised.status_code == 200, revised.text
    assert published.status_code == (200 if first_operation == "publish" else 409), published.text
    get_url = path(db, "exam-blueprints", f"/publications/{second['id']}")
    saved = db.client.get(get_url, headers=coordinator)
    if first_operation == "publish":
        assert saved.json() == published.json()
    else:
        assert saved.status_code == 404
