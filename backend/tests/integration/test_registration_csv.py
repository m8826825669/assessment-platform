"""SCH-01/TEN-01 CSV previews, atomic creation, replay and transport boundaries."""

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import test_exam_sittings
from sqlalchemy import event, text, update
from sqlalchemy.exc import SQLAlchemyError
from test_question_review import context
from test_sitting_cancellations import move_opening_into_past

from app.db.models import Membership
from assessment_core.registration_csv import COLUMNS, MAX_BYTES

pytestmark = pytest.mark.integration
PRIVATE_REASON = "Private synthetic CSV accommodation"


@pytest.fixture
def csv_setup(security_database):
    setup = test_exam_sittings.sitting_setup.__wrapped__(security_database)
    test_exam_sittings.schedule(setup)
    return setup


def csv_bytes(candidates, identities=None, extra=0):
    identities = identities or [uuid4() for _ in candidates]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    for identity, candidate in zip(identities, candidates, strict=True):
        writer.writerow([identity, candidate, str(extra), PRIVATE_REASON if extra else ""])
    return output.getvalue().encode()


def request(setup, data, preview=False, headers=None, suffix=""):
    db, staff, _, _, url, _ = setup
    return db.client.post(
        url + "/registrations/csv" + ("/preview" if preview else "") + suffix,
        headers=headers or {**staff, "Content-Type": "text/csv"},
        content=data,
    )


def counts(db):
    with db.admin_engine.begin() as c:
        context(c, db)
        return tuple(
            c.scalar(text("SELECT count(*) FROM " + name))
            for name in (
                "sitting_registrations",
                "audit_records",
                "outbox_events",
                "outbox_deliveries",
                "users",
                "memberships",
            )
        )


def test_csv_preview_commit_replay_and_json_interoperability(csv_setup):
    db, staff, _, candidates, url, _ = csv_setup
    data = csv_bytes(candidates, extra=15)
    before = counts(db)
    preview = request(csv_setup, data, preview=True)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["valid"] is True and body["new_count"] == 2 and body["replayed_count"] == 0
    assert [row["row"] for row in body["rows"]] == [2, 3]
    assert PRIVATE_REASON not in preview.text and counts(db) == before
    response = request(csv_setup, data)
    assert response.status_code == 200, response.text
    assert [row["allowed_minutes"] for row in response.json()] == [45, 45]
    saved = counts(db)
    assert saved[0] == 2 and saved[-2:] == before[-2:]
    assert request(csv_setup, data).json() == response.json()
    assert counts(db) == saved
    repeated = request(csv_setup, data, preview=True).json()
    assert repeated["replayed_count"] == 2 and repeated["new_count"] == 0
    assert counts(db) == saved
    json_batch = {
        "registrations": [
            {
                key: value
                for key, value in row.items()
                if key in ("id", "candidate_user_id", "extra_minutes", "accommodation_reason")
            }
            for row in response.json()
        ]
    }
    assert db.client.post(url + "/registrations", headers=staff, json=json_batch).json() == response.json()
    assert request(csv_setup, csv_bytes(candidates)).status_code == 409
    assert counts(db) == saved
    assert response.headers["cache-control"] == "no-store"


def test_invalid_csv_never_echoes_cells_or_persists_rows(csv_setup):
    db = csv_setup[0]
    data = b",".join(column.encode() for column in COLUMNS) + b"\nPRIVATE_INVALID_UUID,other,0,\n"
    before = counts(db)
    preview = request(csv_setup, data, preview=True)
    assert preview.status_code == 200 and preview.json()["valid"] is False
    assert preview.json()["diagnostics"] == [{"row": 2, "column": "id", "code": "csv_uuid"}]
    committed = request(csv_setup, data)
    assert committed.status_code == 422
    assert committed.json()["errors"][0]["location"] == ["body", 2, "id"]
    assert "PRIVATE_INVALID_UUID" not in preview.text + committed.text
    assert counts(db) == before


def test_ineligible_csv_candidate_has_row_diagnostic_and_atomic_rejection(csv_setup):
    db, _, _, candidates, _, _ = csv_setup
    data = csv_bytes([candidates[0], uuid4()])
    before = counts(db)
    response = request(csv_setup, data, preview=True)
    assert response.status_code == 200 and response.json()["valid"] is False
    assert response.json()["diagnostics"] == [{"row": 3, "column": None, "code": "candidate_unavailable"}]
    assert response.json()["new_count"] == 1 and counts(db) == before
    assert request(csv_setup, data).status_code == 409
    assert counts(db) == before


@pytest.mark.parametrize("table", ["audit_records", "outbox_events", "outbox_deliveries"])
def test_csv_commit_rolls_back_on_audit_or_outbox_failure(csv_setup, table):
    db, _, _, candidates, _, _ = csv_setup
    data = csv_bytes(candidates)
    before = counts(db)
    engine = db.client.app.state.database.engine
    deliveries = 0

    def fail(connection, cursor, statement, parameters, ctx, executemany):
        nonlocal deliveries
        if statement.startswith("INSERT INTO " + table):
            deliveries += 1
            if deliveries == 2:
                raise SQLAlchemyError("Injected late CSV batch failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = request(csv_setup, data)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 503, response.text
    assert counts(db) == before
    assert request(csv_setup, data).status_code == 200


def test_concurrent_csv_retries_acknowledge_one_batch(csv_setup):
    db, _, _, candidates, _, _ = csv_setup
    data = csv_bytes(candidates)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: request(csv_setup, data), range(2)))
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json() == results[1].json()
    with db.admin_engine.begin() as c:
        context(c, db)
        assert (
            c.scalar(text("SELECT count(*) FROM audit_records WHERE action='exam.candidate_registered'")) == 2
        )


@pytest.mark.parametrize("change", ["candidate_suspended", "cancelled", "opened", "staff_suspended"])
def test_csv_commit_rechecks_state_after_preview(csv_setup, change):
    db, staff, _, candidates, url, _ = csv_setup
    data = csv_bytes([candidates[0]])
    assert request(csv_setup, data, preview=True).json()["valid"] is True
    if change in ("candidate_suspended", "staff_suspended"):
        candidate = candidates[0] if change == "candidate_suspended" else db.ids["candidate"]
        with db.admin_engine.begin() as c:
            context(c, db)
            c.execute(
                update(Membership)
                .where(Membership.tenant_id == db.ids["tenant_a"], Membership.user_id == candidate)
                .values(status="suspended")
            )
    elif change == "cancelled":
        assert (
            db.client.put(
                url + "/cancellation", headers=staff, json={"reason_code": "administrative"}
            ).status_code
            == 200
        )
    else:
        move_opening_into_past(db)
    before = counts(db)
    assert request(csv_setup, data).status_code == (404 if change == "staff_suspended" else 409)
    assert counts(db) == before


def test_csv_replays_do_not_restore_withdrawn_or_cancelled_registrations(csv_setup):
    db, staff, _, candidates, url, _ = csv_setup
    data = csv_bytes([candidates[0]], extra=10)
    original = request(csv_setup, data)
    assert original.status_code == 200
    reg = original.json()[0]
    amendment = url + "/registrations/" + reg["id"] + "/changes/" + str(uuid4())
    assert (
        db.client.put(
            amendment,
            headers=staff,
            json={
                "expected_revision": 1,
                "action": "amend_accommodation",
                "extra_minutes": 20,
                "reason": "Revised synthetic approval",
            },
        ).status_code
        == 200
    )
    preview = request(csv_setup, data, preview=True).json()
    assert preview["rows"][0]["allowed_minutes"] == 40
    assert preview["rows"][0]["effective_allowed_minutes"] == 50
    withdrawal = url + "/registrations/" + reg["id"] + "/changes/" + str(uuid4())
    assert (
        db.client.put(
            withdrawal,
            headers=staff,
            json={"expected_revision": 2, "action": "withdraw", "reason": "Synthetic withdrawal request"},
        ).status_code
        == 200
    )
    assert request(csv_setup, data, preview=True).json()["rows"][0]["registration_status"] == "withdrawn"
    assert request(csv_setup, data).json() == original.json()
    assert (
        db.client.put(url + "/cancellation", headers=staff, json={"reason_code": "operational"}).status_code
        == 200
    )
    move_opening_into_past(db)
    assert request(csv_setup, data).json() == original.json()
    assert request(csv_setup, csv_bytes([candidates[1]])).status_code == 409


@pytest.mark.parametrize(
    "media", ["application/json", "text/plain", "text/csv; charset=latin-1", "text/csv; extra=yes", ""]
)
def test_csv_transport_requires_utf8_csv(csv_setup, media):
    db, staff, _, candidates, _, _ = csv_setup
    before = counts(db)
    response = request(csv_setup, csv_bytes(candidates), headers={**staff, "Content-Type": media})
    assert response.status_code == 415 and counts(db) == before


@pytest.mark.parametrize("preview", [True, False])
def test_csv_byte_limit_covers_stream_without_content_length(csv_setup, preview):
    db, staff, _, _, url, _ = csv_setup
    before = counts(db)
    response = db.client.post(
        url + "/registrations/csv" + ("/preview" if preview else ""),
        headers={**staff, "Content-Type": "text/csv"},
        content=iter([b"x" * 32768, b"y" * 32768, b"z"]),
    )
    assert response.status_code == 413 and counts(db) == before
    assert request(csv_setup, b"x" * (MAX_BYTES + 1), preview=preview).status_code == 413


def test_csv_role_tenant_and_query_boundaries(csv_setup):
    db, staff, reviewer, candidates, url, _ = csv_setup
    data = csv_bytes(candidates)
    before = counts(db)
    assert request(csv_setup, data, headers={**reviewer, "Content-Type": "text/csv"}).status_code == 403
    foreign = url.replace(str(db.ids["tenant_a"]), str(db.ids["tenant_b"]))
    assert (
        db.client.post(
            foreign + "/registrations/csv", headers={**staff, "Content-Type": "text/csv"}, content=data
        ).status_code
        == 404
    )
    assert request(csv_setup, data, suffix="?ignored=yes").status_code == 422
    assert counts(db) == before
    candidate = db.login(candidates[0].hex)
    assert request(csv_setup, data, headers={**candidate, "Content-Type": "text/csv"}).status_code == 403


def test_csv_mixed_replay_and_new_rows_preserve_existing_receipt(csv_setup):
    db, _, _, candidates, _, _ = csv_setup
    identities = [uuid4(), uuid4()]
    first = request(csv_setup, csv_bytes(candidates[:1], identities[:1]))
    assert first.status_code == 200
    mixed = csv_bytes(candidates, identities)
    preview = request(csv_setup, mixed, preview=True).json()
    assert preview["new_count"] == preview["replayed_count"] == 1
    response = request(csv_setup, mixed)
    assert response.status_code == 200 and response.json()[0] == first.json()[0]
    assert counts(db)[0] == 2


def test_csv_authority_is_rechecked_after_body_stream(csv_setup, monkeypatch):
    from app.scheduling import csv_api

    db, _, _, candidates, _, _ = csv_setup
    original_preflight = csv_api.preflight
    checked = []

    def preflight(*args):
        original_preflight(*args)
        checked.append(True)

    monkeypatch.setattr(csv_api, "preflight", preflight)
    before = counts(db)

    def chunks():
        assert checked
        with db.admin_engine.begin() as c:
            context(c, db)
            c.execute(
                update(Membership)
                .where(Membership.id == db.ids["membership_candidate"])
                .values(status="suspended")
            )
        yield csv_bytes(candidates)

    response = request(csv_setup, chunks())
    assert response.status_code == 404
    # The fixture intentionally changed staff membership; no registration was created.
    assert counts(db)[0] == before[0]
