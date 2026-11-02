"""P2-004 catalogue, immutable version classification and scoped retrieval filters."""

from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.audit import service as audit
from app.db.models import QuestionReviewEvent, QuestionVersionTaxon, TaxonomyTerm
from app.identity.service import reject
from app.question_bank import service
from app.question_bank.contracts import Identifier, Label

Kind = Literal["subject", "topic", "outcome", "tag"]
State = Literal["draft", "in_review", "returned", "approved", "retired", "superseded"]
ItemKind = Literal[
    "single_choice", "multiple_select", "numeric", "short_answer", "essay", "file_upload", "passage_group"
]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class TermCreate(Input):
    kind: Kind
    code: Identifier
    label: Annotated[Label, Field(max_length=200)]
    parent_id: UUID | None = None

    @model_validator(mode="after")
    def topic_parent(self):
        if (self.kind == "topic") != (self.parent_id is not None):
            raise ValueError("Only topics require a subject parent")
        return self


class TermUpdate(Input):
    expected_revision: Annotated[StrictInt, Field(ge=1, le=2147483646)]
    label: Annotated[Label, Field(max_length=200)] | None = None
    state: Literal["active", "retired"] | None = None

    @model_validator(mode="after")
    def change_required(self):
        if self.label is None and self.state is None:
            raise ValueError("Specify label or state")
        return self


class Classification(Input):
    taxonomy_ids: Annotated[tuple[UUID, ...], Field(max_length=64)] = ()

    @field_validator("taxonomy_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Taxonomy references must be distinct")
        return value


class SearchFilters(Classification):
    q: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    kind: ItemKind | None = None
    state: State | None = None

    @field_validator("q")
    @classmethod
    def search_text(cls, value):
        if value is not None:
            value = value.strip()
            if not value or any(ord(char) < 32 for char in value):
                raise ValueError("Use nonblank single-line search text")
        return value


def term_state(term):
    return {"term_id": str(term.id), "term_revision": term.revision, "term_state": term.state}


def get_term(db, tenant, identifier):
    term = db.scalar(
        select(TaxonomyTerm)
        .where(TaxonomyTerm.tenant_id == tenant, TaxonomyTerm.id == identifier)
        .execution_options(populate_existing=True)
    )
    if term is None:
        reject(404, "taxonomy_not_found", "Taxonomy term not found")
    return term


def validate_parent(db, tenant, body):
    if body.kind == "topic":
        parent = get_term(db, tenant, body.parent_id)
        if parent.kind != "subject" or parent.state != "active":
            reject(409, "taxonomy_conflict", "Taxonomy changed or conflicts; reload before retrying")


def create_term(db, tenant, actor, body):
    service.authority(db, tenant, actor, lock=True, permission="taxonomy.manage")
    validate_parent(db, tenant, body)
    term = TaxonomyTerm(
        id=uuid4(),
        tenant_id=tenant,
        created_by=actor.user_id,
        kind=body.kind,
        code=body.code,
        label=body.label,
        parent_id=body.parent_id,
        state="active",
        revision=1,
    )
    try:
        db.add(term)
        db.flush()
        audit.record(db, "taxonomy.created", actor.user_id, tenant, str(term.id), after=term_state(term))
        db.commit()
    except IntegrityError:
        db.rollback()
        reject(409, "taxonomy_conflict", "Taxonomy changed or conflicts; reload before retrying")
    return term


def update_term(db, tenant, actor, identifier, body):
    service.authority(db, tenant, actor, lock=True, permission="taxonomy.manage")
    term = get_term(db, tenant, identifier)
    if term.revision != body.expected_revision or term.state != "active":
        reject(409, "taxonomy_conflict", "Taxonomy changed or conflicts; reload before retrying")
    if body.state == "retired" and db.scalar(
        select(TaxonomyTerm.id)
        .where(
            TaxonomyTerm.tenant_id == tenant,
            TaxonomyTerm.parent_id == identifier,
            TaxonomyTerm.state == "active",
        )
        .limit(1)
    ):
        reject(409, "taxonomy_conflict", "Taxonomy changed or conflicts; reload before retrying")
    before = term_state(term)
    try:
        if body.label is not None:
            term.label = body.label
        if body.state is not None:
            term.state = body.state
        term.revision += 1
        db.flush()
        audit.record(
            db, "taxonomy.changed", actor.user_id, tenant, str(term.id), before=before, after=term_state(term)
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        reject(409, "taxonomy_conflict", "Taxonomy changed or conflicts; reload before retrying")
    return term


def catalogue(db, tenant, actor, kind, state, offset, limit):
    service.authority(db, tenant, actor, permission="taxonomy.read")
    query = select(TaxonomyTerm).where(TaxonomyTerm.tenant_id == tenant)
    if kind:
        query = query.where(TaxonomyTerm.kind == kind)
    if state:
        query = query.where(TaxonomyTerm.state == state)
    return list(
        db.scalars(
            query.order_by(TaxonomyTerm.kind, TaxonomyTerm.code, TaxonomyTerm.id).offset(offset).limit(limit)
        )
    )


def resolve(db, tenant, ids, *, active=True):
    if not ids:
        return []
    terms = list(
        db.scalars(select(TaxonomyTerm).where(TaxonomyTerm.tenant_id == tenant, TaxonomyTerm.id.in_(ids)))
    )
    if len(terms) != len(set(ids)) or (active and any(term.state != "active" for term in terms)):
        reject(404, "taxonomy_not_found", "Taxonomy term not found")
    return terms


def classification_terms(db, tenant, ids):
    terms = resolve(db, tenant, ids)
    parents = {term.parent_id for term in terms if term.parent_id} - {term.id for term in terms}
    terms += resolve(db, tenant, tuple(parents))
    if len(terms) > 64:
        reject(422, "taxonomy_limit", "Use at most 64 taxonomy references including subject parents")
    return terms


def capture(db, row, saved, ids):
    terms = classification_terms(db, row.tenant_id, ids)
    # Subject links are flushed first so topic links can require their frozen parent reference.
    for subject_pass in [True, False]:
        for term in terms:
            if (term.kind == "subject") != subject_pass:
                continue
            db.add(
                QuestionVersionTaxon(
                    tenant_id=row.tenant_id,
                    question_id=row.id,
                    version_id=saved.id,
                    term_id=term.id,
                    kind_snapshot=term.kind,
                    code_snapshot=term.code,
                    label_snapshot=term.label,
                    parent_id_snapshot=term.parent_id,
                    term_revision=term.revision,
                )
            )
        db.flush()


def snapshots(db, tenant, version_id):
    query = (
        select(
            QuestionVersionTaxon.term_id,
            QuestionVersionTaxon.kind_snapshot,
            QuestionVersionTaxon.code_snapshot,
            QuestionVersionTaxon.label_snapshot,
            QuestionVersionTaxon.parent_id_snapshot,
            QuestionVersionTaxon.term_revision,
        )
        .where(QuestionVersionTaxon.tenant_id == tenant, QuestionVersionTaxon.version_id == version_id)
        .order_by(
            QuestionVersionTaxon.kind_snapshot,
            QuestionVersionTaxon.code_snapshot,
            QuestionVersionTaxon.term_id,
        )
    )
    return [
        {
            "id": identifier,
            "kind": kind,
            "code": code,
            "label": label,
            "parent_id": parent,
            "revision": revision,
        }
        for identifier, kind, code, label, parent, revision in db.execute(query)
    ]


def apply_filters(db, tenant, query, model, filters, *, public=False, queue=False):
    if filters is None:
        return query
    resolve(db, tenant, filters.taxonomy_ids, active=False)
    if filters.q is not None:
        query = query.where(model.title.icontains(filters.q, autoescape=True))
    if filters.kind:
        content = model.public_content if public else model.content
        query = query.where(content["kind"].astext == filters.kind)
    for identifier in filters.taxonomy_ids:
        query = query.where(
            select(QuestionVersionTaxon.term_id)
            .where(
                QuestionVersionTaxon.tenant_id == tenant,
                QuestionVersionTaxon.version_id == (model.version_id if public else model.id),
                QuestionVersionTaxon.term_id == identifier,
            )
            .exists()
        )
    if filters.state:
        if public or queue:
            expected = "approved" if public else "in_review"
            if filters.state != expected:
                reject(422, "invalid_search", "Unsupported state for this collection")
        else:
            current = (
                select(QuestionReviewEvent.state)
                .where(QuestionReviewEvent.tenant_id == tenant, QuestionReviewEvent.version_id == model.id)
                .order_by(QuestionReviewEvent.sequence.desc())
                .limit(1)
                .scalar_subquery()
            )
            query = query.where(func.coalesce(current, "draft") == filters.state)
    return query


def search_params(
    request: Request,
    q: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    kind: ItemKind | None = None,
    state: State | None = None,
    taxonomy_ids: Annotated[list[UUID] | None, Query(max_length=64)] = None,
) -> SearchFilters:
    from fastapi.exceptions import RequestValidationError
    from pydantic import ValidationError

    allowed = {"q", "kind", "state", "taxonomy_ids", "offset", "limit"}
    invalid = set(request.query_params) - allowed
    invalid.update(key for key in allowed - {"taxonomy_ids"} if len(request.query_params.getlist(key)) > 1)
    if invalid:
        raise RequestValidationError(
            [
                {"loc": ("query", key), "type": "extra_forbidden", "msg": "Invalid query parameter"}
                for key in sorted(invalid)
            ]
        )
    try:
        return SearchFilters(q=q, kind=kind, state=state, taxonomy_ids=tuple(taxonomy_ids or ()))
    except ValidationError as error:
        raise RequestValidationError(
            [{**item, "loc": ("query", *item["loc"])} for item in error.errors()]
        ) from None
