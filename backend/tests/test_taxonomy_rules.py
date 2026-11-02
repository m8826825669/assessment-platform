"""P2-004 bounded input and query contracts; database semantics tested separately."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.audit.service import clean_state
from app.question_bank.api import Filters
from app.question_bank.taxonomy import Classification, SearchFilters, TermCreate, TermUpdate


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "topic"},
        {"kind": "subject", "parent_id": str(uuid4())},
        {"code": "Upper"},
        {"code": "bad space"},
        {"label": " "},
        {"label": "x" * 201},
        {"kind": "unknown"},
        {"state": "retired"},
    ],
)
def test_invalid_catalogue_input(change):
    with pytest.raises(ValidationError):
        TermCreate.model_validate({"kind": "subject", "code": "math", "label": "Mathematics", **change})


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"expected_revision": True, "label": "New"},
        {"expected_revision": 0, "label": "New"},
        {"expected_revision": 1},
        {"expected_revision": 1, "code": "new"},
        {"expected_revision": 1, "state": "deleted"},
    ],
)
def test_invalid_term_changes(body):
    with pytest.raises(ValidationError):
        TermUpdate.model_validate(body)


def test_classification_has_explicit_bounds_and_no_duplicates():
    identifier = uuid4()
    assert Classification().taxonomy_ids == ()
    for ids in [[identifier, identifier], [uuid4() for _ in range(65)], ["bad"]]:
        with pytest.raises(ValidationError):
            Classification(taxonomy_ids=ids)


@pytest.mark.parametrize("query", [" ", "\n", "x\ny", "x" * 161])
def test_search_rejects_blank_multiline_or_unbounded_input(query):
    with pytest.raises(ValidationError):
        SearchFilters(q=query)


@pytest.mark.parametrize(
    "params",
    [
        {"q": " "},
        {"kind": "unknown"},
        {"state": "unknown"},
        {"taxonomy_ids": "bad"},
        [("q", "one"), ("q", "two")],
        {"unexpected": "value"},
        [("taxonomy_ids", "00000000-0000-0000-0000-000000000001")] * 2,
    ],
)
def test_http_query_dependency_rejects_ambiguous_or_malformed_filters(params):
    app = FastAPI()

    @app.get("/")
    def endpoint(filters: Filters):
        return filters.model_dump(mode="json")

    with TestClient(app) as client:
        assert client.get("/", params=params).status_code == 422


def test_http_query_dependency_preserves_literal_text_and_and_references():
    app = FastAPI()

    @app.get("/")
    def endpoint(filters: Filters):
        return filters.model_dump(mode="json")

    identifiers = [str(uuid4()), str(uuid4())]
    with TestClient(app) as client:
        result = client.get(
            "/", params=[("q", "  50%_ / text  "), *[("taxonomy_ids", i) for i in identifiers]]
        )
    assert result.status_code == 200
    assert result.json()["q"] == "50%_ / text"
    assert result.json()["taxonomy_ids"] == identifiers


@pytest.mark.parametrize("action", ["taxonomy.created", "taxonomy.changed"])
def test_taxonomy_audit_excludes_catalogue_labels_and_arbitrary_payloads(action):
    assert clean_state(action, {"term_id": str(uuid4()), "term_revision": 1, "term_state": "active"})
    for body in [
        {"label": "private"},
        {"code": "private"},
        {"term_revision": True},
        {"term_state": "deleted"},
    ]:
        with pytest.raises(ValueError):
            clean_state(action, body)
