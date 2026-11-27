"""TEN-01/PUB-01/SEC-01 publication access boundaries."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from test_question_review import approve, context, create, path, prepare, submit

from app.db.models import Membership, QuestionVersion
from app.question_bank.contracts import candidate_view, validate_content

pytestmark = pytest.mark.integration


@pytest.fixture
def approved_exam(security_database):
    db = security_database
    author, reviewer, coordinator = prepare(db)
    question = approve(db, reviewer, submit(db, author, create(db, author)))
    draft_id = uuid4()
    url = path(db, "exam-blueprints", f"/drafts/{draft_id}")
    response = db.client.put(
        url,
        headers=coordinator,
        json={
            "sections": [
                {
                    "version_ids": [question["version_id"]],
                    "minimum": 1,
                    "maximum": 1,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    get_url = path(db, "exam-blueprints", f"/publications/{draft_id}")
    return db, question, coordinator, url + "/publish", get_url


@pytest.mark.parametrize("flag", ["on", "off", "true", "1"])
def test_coordinator_cannot_enable_private_source_reads(approved_exam, flag):
    db, question, coordinator, publish_url, get_url = approved_exam
    with db.runtime_engine.begin() as connection:
        context(connection, db, "candidate")
        connection.execute(
            text("SELECT set_config('app.publication_read', :flag, true)"),
            {"flag": flag},
        )
        assert (
            connection.scalar(
                select(QuestionVersion.content).where(QuestionVersion.id == UUID(question["version_id"]))
            )
            is None
        )

    response = db.client.post(publish_url, headers=coordinator)
    assert response.status_code == 200, response.text
    assert response.json() == db.client.get(get_url, headers=coordinator).json()
    assert "grading" not in response.json()
    item = response.json()["sections"][0]["items"][0]
    assert item["content"] == candidate_view(validate_content(question["content"]))

    with db.runtime_engine.begin() as connection:
        context(connection, db, "candidate")
        snapshot = connection.scalar(
            text("SELECT snapshot FROM exam_publications WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": db.ids["tenant_a"], "id": UUID(response.json()["id"])},
        )
    assert set(snapshot["grading"][question["version_id"]]) == {"version_id", "approval_event_id"}


def test_publication_access_rechecks_current_role(approved_exam):
    db, question, coordinator, publish_url, get_url = approved_exam
    assert db.client.post(publish_url, headers=coordinator).status_code == 200
    with db.admin_engine.begin() as connection:
        context(connection, db)
        connection.execute(
            update(Membership).where(Membership.id == db.ids["membership_candidate"]).values(role="candidate")
        )
    assert db.client.get(get_url, headers=coordinator).status_code == 403
    assert db.client.post(publish_url, headers=coordinator).status_code == 403
    with db.runtime_engine.begin() as connection:
        context(connection, db, "candidate")
        assert connection.scalar(text("SELECT count(*) FROM exam_publications")) == 0


def test_wrong_tenant_cannot_read_publication_or_source(approved_exam):
    db, question, coordinator, publish_url, get_url = approved_exam
    assert db.client.post(publish_url, headers=coordinator).status_code == 200
    foreign = get_url.replace(str(db.ids["tenant_a"]), str(db.ids["tenant_b"]))
    assert db.client.get(foreign, headers=coordinator).status_code == 404
    with db.runtime_engine.begin() as connection:
        context(connection, db, "candidate", tenant="b")
        connection.execute(text("SELECT set_config('app.publication_read', 'on', true)"))
        assert connection.scalar(text("SELECT count(*) FROM exam_publications")) == 0
        assert connection.scalar(select(QuestionVersion.content)) is None


def test_readiness_rejects_restored_publication_bypass(security_database):
    db = security_database
    with db.admin_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE POLICY question_version_publication_read "
                "ON question_versions FOR SELECT USING (false)"
            )
        )
    response = db.client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"]["schema"] == "not_ready"
