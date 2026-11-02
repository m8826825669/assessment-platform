"""Real PostgreSQL media invariants. Fakes isolate SQL/API tests; live S3/ClamAV tests are separate."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from PIL import Image
from sqlalchemy import event, text, update
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.db.models import Membership, QuestionVersionMedia
from app.media.adapters import MediaUnavailable

pytestmark = pytest.mark.integration
CONTENT = json.loads(
    (Path(__file__).resolve().parents[3] / "docs/QUESTION_CONTENT_EXAMPLES.json").read_text()
)[0]


class MemoryStore:
    def __init__(self):
        self.objects = {}

    def ready(self):
        pass

    def put(self, key, data, mime):
        version = str(uuid4())
        self.objects[(key, version)] = data
        return version

    def get(self, key, version, digest, length):
        data = self.objects.get((key, version))
        if data is None or len(data) != length or sha256(data).hexdigest() != digest:
            raise MediaUnavailable()
        return data


class ControlledScanner:
    verdict = "clean"
    unavailable = False

    def ready(self):
        return "ClamAV fixture"

    def scan(self, data):
        if self.unavailable:
            raise MediaUnavailable()
        return self.verdict, "ClamAV fixture"


@pytest.fixture
def media_db(security_database):
    db = security_database
    gateway = SimpleNamespace(store=MemoryStore(), scanner=ControlledScanner())
    gateway.ready = lambda: {"media_storage": "ok", "media_scanner": "ok"}
    db.client.app.state.media = gateway
    return db


def path(db, suffix="", kind="media", tenant="a"):
    return f"/api/v1/tenants/{db.ids['tenant_' + tenant]}/{kind}" + suffix


def context(connection, db, actor="admin_a"):
    connection.execute(text("SELECT set_config('app.tenant_id',:id,true)"), {"id": str(db.ids["tenant_a"])})
    connection.execute(text("SELECT set_config('app.actor_user_id',:id,true)"), {"id": str(db.ids[actor])})


def png():
    stream = io.BytesIO()
    Image.new("RGB", (4, 3), "green").save(stream, format="PNG")
    return stream.getvalue()


def reserve(db, who):
    response = db.client.post(
        path(db),
        headers=who,
        json={
            "filename": "diagram.png",
            "mime_type": "image/png",
            "description": "A green rectangle with four corners",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(db, who, asset, data=None):
    return db.client.put(
        path(db, "/" + asset["asset_id"] + "/content"),
        headers={**who, "Content-Type": "image/png"},
        params={"expected_revision": asset["revision"]},
        content=data if data is not None else png(),
    )


def scan(db, who, asset):
    return db.client.post(
        path(db, "/" + asset["asset_id"] + "/scan"),
        headers=who,
        json={"expected_revision": asset["revision"]},
    )


def clean(db, who):
    asset = reserve(db, who)
    response = upload(db, who, asset)
    assert response.status_code == 200, response.text
    response = scan(db, who, response.json())
    assert response.status_code == 200 and response.json()["state"] == "clean", response.text
    return response.json()


def question(db, who, ids):
    return db.client.post(
        path(db, kind="questions"),
        headers=who,
        json={"title": "Diagram question", "content": CONTENT, "media_ids": ids},
    )


def decide(db, who, row, action):
    response = db.client.post(
        path(db, f"/{row['question_id']}/versions/{row['version_id']}", kind="question-reviews"),
        headers=who,
        json={
            "action": action,
            "expected_revision": row["revision"],
            "expected_review_revision": row["review_revision"],
            "content_hash": row["content_hash"],
        },
    )
    return response


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


def test_clean_image_journey_freezes_reference_and_excludes_storage_secrets(media_db):
    db = media_db
    admin, reviewer, coordinator = prepare(db)
    asset = clean(db, admin)
    row = question(db, admin, [asset["asset_id"]])
    assert row.status_code == 201, row.text
    row = row.json()
    assert row["media"][0]["description"] == asset["description"]
    assert not {"object_key", "object_version", "digest", "scanner_version"} & row["media"][0].keys()
    download = path(db, "/" + asset["asset_id"] + "/content")
    assert db.client.get(download, headers=reviewer).status_code == 404
    assert db.client.get(download, headers=coordinator).status_code == 404
    submitted = decide(db, admin, row, "submit")
    assert submitted.status_code == 200, submitted.text
    assert db.client.get(download, headers=reviewer).content == png()
    approved = decide(db, reviewer, submitted.json(), "approve")
    assert approved.status_code == 200, approved.text
    selected = db.client.get(path(db, kind="question-selections"), headers=coordinator)
    assert selected.status_code == 200 and selected.json()[0]["media"] == row["media"]
    response = db.client.get(download, headers=coordinator)
    assert response.status_code == 200 and response.content == png()
    public_metadata = db.client.get(path(db, "/" + asset["asset_id"]), headers=coordinator)
    assert public_metadata.status_code == 200
    assert "filename" not in public_metadata.json() and "error_code" not in public_metadata.json()
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    preview = db.client.get(path(db, "/" + row["question_id"] + "/preview", kind="questions"), headers=admin)
    assert preview.json()["media"] == row["media"] and "correct_option_id" not in preview.text
    revision = db.client.post(
        path(db, "/" + row["question_id"] + "/versions", kind="questions"),
        headers=admin,
        json={"title": "New draft", "content": CONTENT, "expected_revision": 1},
    )
    assert revision.status_code == 201 and revision.json()["media"] == []
    assert db.client.get(path(db, kind="question-selections"), headers=coordinator).json() == selected.json()


@pytest.mark.parametrize("stage", ["pending", "quarantine", "rejected"])
def test_unclean_media_cannot_download_or_attach(media_db, stage):
    db = media_db
    admin = db.login("admin_a")
    asset = reserve(db, admin)
    if stage != "pending":
        asset = upload(db, admin, asset).json()
    if stage == "rejected":
        db.client.app.state.media.scanner.verdict = "rejected"
        asset = scan(db, admin, asset).json()
    assert db.client.get(path(db, "/" + asset["asset_id"] + "/content"), headers=admin).status_code == 409
    assert question(db, admin, [asset["asset_id"]]).status_code == 409
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(text("SELECT count(*) FROM questions")) == 0


def test_scanner_failure_retains_quarantine_and_fenced_retry(media_db):
    db = media_db
    admin = db.login("admin_a")
    asset = upload(db, admin, reserve(db, admin)).json()
    db.client.app.state.media.scanner.unavailable = True
    result = scan(db, admin, asset)
    assert (
        result.status_code == 200
        and result.json()["state"] == "quarantine"
        and result.json()["error_code"] == "scan_unavailable"
    )
    assert scan(db, admin, asset).status_code == 409
    db.client.app.state.media.scanner.unavailable = False
    assert scan(db, admin, result.json()).json()["state"] == "clean"


def test_missing_or_changed_stored_bytes_fail_attachment_review_and_download(media_db):
    db = media_db
    admin, reviewer, _ = prepare(db)
    asset = clean(db, admin)
    row = question(db, admin, [asset["asset_id"]]).json()
    saved = dict(db.client.app.state.media.store.objects)
    db.client.app.state.media.store.objects.clear()
    assert question(db, admin, [asset["asset_id"]]).status_code == 503
    assert decide(db, admin, row, "submit").status_code == 503
    assert db.client.get(path(db, "/" + asset["asset_id"] + "/content"), headers=admin).status_code == 503
    db.client.app.state.media.store.objects = saved
    submitted = decide(db, admin, row, "submit").json()
    db.client.app.state.media.store.objects = {key: b"corrupt" for key in saved}
    assert decide(db, reviewer, submitted, "approve").status_code == 503
    db.client.app.state.media.store.objects = saved
    approved = decide(db, reviewer, submitted, "approve")
    assert approved.status_code == 200
    db.client.app.state.media.store.objects.clear()
    assert db.client.get(path(db, kind="question-selections"), headers=admin).status_code == 503


@pytest.mark.parametrize("role", ["candidate", "invigilator", "examiner", "reviewer", "coordinator"])
def test_non_authoring_roles_cannot_reserve_upload_or_scan(media_db, role):
    db = media_db
    admin = db.login("admin_a")
    asset = reserve(db, admin)
    with db.admin_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            update(Membership).where(Membership.id == db.ids["membership_candidate"]).values(role=role)
        )
    who = db.login("candidate")
    assert (
        db.client.post(
            path(db),
            headers=who,
            json={"filename": "x.png", "mime_type": "image/png", "description": "Triangle diagram"},
        ).status_code
        == 403
    )
    assert upload(db, who, asset).status_code == 403
    assert scan(db, who, asset).status_code == 403


def test_foreign_and_other_author_media_is_not_discoverable(media_db):
    db = media_db
    admin = db.login("admin_a")
    asset = clean(db, admin)
    other = db.login("admin_b")
    assert db.client.get(path(db, "/" + asset["asset_id"], tenant="b"), headers=other).status_code == 404
    assert question(db, other, [asset["asset_id"]]).status_code == 404
    with db.admin_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            update(Membership).where(Membership.id == db.ids["membership_candidate"]).values(role="author")
        )
    author = db.login("candidate")
    assert db.client.get(path(db, "/" + asset["asset_id"]), headers=author).status_code == 404
    assert question(db, author, [asset["asset_id"]]).status_code == 404


@pytest.mark.parametrize("data,status", [(b"not an image", 422), (b"x" * (8388608 + 1), 413)])
def test_invalid_or_oversized_bytes_never_reach_object_store(media_db, data, status):
    db = media_db
    admin = db.login("admin_a")
    asset = reserve(db, admin)
    assert upload(db, admin, asset, data).status_code == status
    assert db.client.app.state.media.store.objects == {}


def test_duplicate_concurrent_uploads_have_one_winner(media_db):
    db = media_db
    admin = db.login("admin_a")
    asset = reserve(db, admin)
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: upload(db, admin, asset).status_code, range(2)))
    assert sorted(statuses) == [200, 409]
    assert len(db.client.app.state.media.store.objects) == 1


@pytest.mark.parametrize("operation", ["reserve", "upload", "scan", "attach"])
def test_media_state_and_audit_roll_back_with_outbox_failure(media_db, operation):
    db = media_db
    admin = db.login("admin_a")
    asset = reserve(db, admin) if operation in ["upload", "scan"] else None
    if operation == "scan":
        asset = upload(db, admin, asset).json()
    if operation == "attach":
        asset = clean(db, admin)
    engine = db.client.app.state.database.engine

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        if statement.startswith("INSERT INTO outbox_deliveries"):
            raise SQLAlchemyError("Injected failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        if operation == "reserve":
            response = db.client.post(
                path(db),
                headers=admin,
                json={"filename": "x.png", "mime_type": "image/png", "description": "Triangle diagram"},
            )
        elif operation == "upload":
            response = upload(db, admin, asset)
        elif operation == "scan":
            response = scan(db, admin, asset)
        else:
            response = question(db, admin, [asset["asset_id"]])
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(text("SELECT count(*) FROM question_version_media")) == 0
        if asset:
            assert connection.scalar(text("SELECT revision FROM media_assets")) == asset["revision"]
        else:
            assert connection.scalar(text("SELECT count(*) FROM media_assets")) == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE media_assets SET description='Changed'",
        "DELETE FROM media_assets",
        "TRUNCATE media_assets",
        "DELETE FROM question_version_media",
        "TRUNCATE question_version_media",
    ],
)
def test_runtime_cannot_rewrite_frozen_media_or_erase_history(media_db, statement):
    db = media_db
    admin = db.login("admin_a")
    asset = clean(db, admin)
    assert question(db, admin, [asset["asset_id"]]).status_code == 201
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db)
        connection.execute(text(statement))


def test_late_media_link_and_clean_byte_replacement_are_rejected_by_database(media_db):
    db = media_db
    admin = db.login("admin_a")
    asset = clean(db, admin)
    row = question(db, admin, []).json()
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            QuestionVersionMedia.__table__.insert().values(
                tenant_id=db.ids["tenant_a"],
                question_id=UUID(row["question_id"]),
                version_id=UUID(row["version_id"]),
                asset_id=UUID(asset["asset_id"]),
            )
        )
    with pytest.raises(DBAPIError), db.runtime_engine.begin() as connection:
        context(connection, db)
        connection.execute(text("UPDATE media_assets SET object_version='forged',revision=revision+1"))


def test_media_worker_receives_only_safe_envelope_no_media_data(outbox_database):
    db = outbox_database
    gateway = SimpleNamespace(store=MemoryStore(), scanner=ControlledScanner())
    db.client.app.state.media = gateway
    admin = db.login("admin_a")
    clean(db, admin)
    assert db.worker.run_once(100).get("delivered") == 4
    for table in ["media_assets", "question_version_media"]:
        with pytest.raises(DBAPIError), db.worker_database.engine.begin() as connection:
            connection.execute(text("SELECT * FROM " + table))


def test_database_rejects_service_attempt_to_link_unclean_asset(media_db):
    db = media_db
    admin = db.login("admin_a")
    approved_asset = clean(db, admin)
    pending = reserve(db, admin)

    def tamper(mapper, connection, target):
        target.asset_id = UUID(pending["asset_id"])

    event.listen(QuestionVersionMedia, "before_insert", tamper)
    try:
        response = question(db, admin, [approved_asset["asset_id"]])
    finally:
        event.remove(QuestionVersionMedia, "before_insert", tamper)
    assert response.status_code == 409
    with db.admin_engine.begin() as connection:
        context(connection, db)
        assert connection.scalar(text("SELECT count(*) FROM question_version_media")) == 0
        assert connection.scalar(text("SELECT count(*) FROM questions")) == 0


@pytest.mark.parametrize("revocation,status", [("role", 403), ("session", 401)])
def test_media_mutation_rechecks_authority_after_waiting_for_lock(media_db, revocation, status):
    from threading import Event

    from app.db.models import AuthSession

    db = media_db
    admin = db.login("admin_a")
    asset = upload(db, admin, reserve(db, admin)).json()
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
                pending = executor.submit(scan, db, admin, asset)
                assert reached.wait(3)
                if revocation == "role":
                    connection.execute(
                        update(Membership)
                        .where(Membership.id == db.ids["membership_a"])
                        .values(role="coordinator")
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


def test_retired_selection_does_not_leave_coordinator_media_access(media_db):
    db = media_db
    admin, reviewer, coordinator = prepare(db)
    asset = clean(db, admin)
    row = question(db, admin, [asset["asset_id"]]).json()
    submitted = decide(db, admin, row, "submit").json()
    approved = decide(db, reviewer, submitted, "approve").json()
    response = db.client.post(
        path(db, f"/{row['question_id']}/versions/{row['version_id']}", kind="question-reviews"),
        headers=reviewer,
        json={
            "action": "retire",
            "reason": "Diagram no longer current",
            "expected_revision": approved["revision"],
            "expected_review_revision": approved["review_revision"],
            "content_hash": approved["content_hash"],
        },
    )
    assert response.status_code == 200, response.text
    assert (
        db.client.get(path(db, "/" + asset["asset_id"] + "/content"), headers=coordinator).status_code == 404
    )
    assert db.client.get(path(db, kind="question-selections"), headers=coordinator).json() == []
    # Historical review and the originating author retain their explicitly authorized access.
    assert db.client.get(path(db, "/" + asset["asset_id"] + "/content"), headers=admin).status_code == 200
