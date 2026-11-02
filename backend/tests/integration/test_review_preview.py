"""P2-007: server projection for reviewer browser traffic; no marking keys."""

import pytest
from test_question_review import decide, prepare, review_path
from test_question_versions import EXAMPLES, create

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("content", EXAMPLES, ids=[c["kind"] for c in EXAMPLES])
def test_reviewer_preview_has_only_public_content(security_database, content):
    from app.question_bank.contracts import candidate_view, validate_content

    db = security_database
    author, reader, coordinator = prepare(db)
    row = create(db, author, content)
    endpoint = review_path(db, row) + "/preview"
    assert db.client.get(endpoint, headers=reader).status_code == 404
    assert decide(db, author, row, "submit").status_code == 200
    response = db.client.get(endpoint, headers=reader)
    assert response.status_code == 200
    assert response.json()["content"] == candidate_view(validate_content(content))
    assert set(response.json()) == {"question_id", "version_id", "content", "media"}
    assert response.headers["cache-control"] == "no-store"
    assert db.client.get(endpoint, headers=db.login("admin_b")).status_code == 404
    assert db.client.get(endpoint, headers=coordinator).status_code == 403
    assert db.client.get(endpoint).status_code == 401
