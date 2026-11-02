"""Content/HTTP/audit contracts only; no database claims."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.audit.service import clean_state
from app.config import Settings
from app.identity.api import get_principal
from app.identity.service import Principal
from app.main import create_app
from app.question_bank import service
from app.question_bank.api import QuestionCreate, QuestionRevise

EXAMPLE = json.loads(
    (Path(__file__).resolve().parents[2] / "docs/QUESTION_CONTENT_EXAMPLES.json").read_text()
)[0]


@pytest.mark.parametrize(
    "change",
    [
        {"expected_revision": True},
        {"expected_revision": 0},
        {"expected_revision": "1"},
        {"expected_revision": 2147483647},
        {"title": " "},
        {"title": "x" * 201},
        {"state": "approved"},
    ],
)
def test_write_contract_rejects_invalid_fences_titles_and_privileged_fields(change):
    with pytest.raises(ValidationError):
        QuestionRevise.model_validate(
            {"expected_revision": 1, "title": "Valid", "content": EXAMPLE, **change}
        )


def test_revision_is_not_accepted_in_create_body():
    with pytest.raises(ValidationError):
        QuestionCreate.model_validate({"expected_revision": 1, "title": "Valid", "content": EXAMPLE})


@pytest.mark.parametrize("action", ["question.created", "question.revised"])
def test_audit_state_accepts_only_safe_version_metadata(action):
    state = {"version_id": str(uuid4()), "revision": 2, "content_hash": "a" * 64}
    assert clean_state(action, state) == state
    for field in ["title", "content", "prompt", "correct_option_id", "marker_guidance"]:
        with pytest.raises(ValueError):
            clean_state(action, {field: "private"})


@pytest.mark.parametrize(
    "state",
    [
        {"version_id": "invalid"},
        {"revision": True},
        {"revision": 0},
        {"revision": 2147483648},
        {"content_hash": "not-a-digest"},
        {"content_hash": 23},
    ],
)
def test_invalid_audit_metadata_rejected(state):
    with pytest.raises(ValueError):
        clean_state("question.revised", state)


def test_question_http_validation_never_echoes_private_content(monkeypatch):
    app = create_app(
        Settings(_env_file=None, database_url="postgresql+psycopg://probe@localhost:1/disposable")
    )
    app.dependency_overrides[get_principal] = lambda: Principal(
        uuid4(), uuid4(), "fixture@example.test", "Fixture"
    )
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/tenants/{uuid4()}/questions",
            json={
                "title": "Private authoring title",
                "content": {**EXAMPLE, "correct_option_id": "private_missing_answer"},
            },
        )
        assert response.status_code == 422
        assert "private_missing_answer" not in response.text
        assert "Private authoring title" not in response.text
        assert response.headers["content-type"] == "application/problem+json"


def test_revision_conflict_has_stable_problem_code(monkeypatch):
    from app.identity.service import reject

    app = create_app(
        Settings(_env_file=None, database_url="postgresql+psycopg://probe@localhost:1/disposable")
    )
    app.dependency_overrides[get_principal] = lambda: Principal(
        uuid4(), uuid4(), "fixture@example.test", "Fixture"
    )

    def conflict(*args):
        reject(409, "question_conflict", "Never serialized arbitrary detail")

    monkeypatch.setattr(service, "revise", conflict)
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/tenants/{uuid4()}/questions/{uuid4()}/versions",
            json={
                "expected_revision": 1,
                "title": "Valid",
                "content": EXAMPLE,
            },
        )
    assert response.status_code == 409
    assert response.json()["code"] == "question_conflict"
    assert "Never serialized" not in response.text
