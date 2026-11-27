"""Coordinator validation of an unsaved fixed exam blueprint."""

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert

from app.audit.service import record
from app.db.models import ExamBlueprintDraft, ExamPublication, QuestionSelection, QuestionVersionTaxon
from app.identity.api import Actor, Db
from app.identity.service import reject
from app.media.service import checked_bytes, describe, version_assets
from app.question_bank.review import access
from app.question_bank.taxonomy import snapshots as taxonomy_snapshots
from assessment_core.blueprint import ApprovedSelection, CoverageRule, Section, validate_blueprint
from assessment_core.publication import build_snapshot

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["exam blueprints"])
Count = Annotated[int, Field(strict=True, ge=0, le=500)]


class CoverageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term_id: UUID
    minimum: Count
    maximum: Count


class SectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_ids: Annotated[tuple[UUID, ...], Field(max_length=100)]
    minimum: Count
    maximum: Count
    coverage: Annotated[tuple[CoverageBody, ...], Field(max_length=25)] = ()


class BlueprintBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sections: Annotated[tuple[SectionBody, ...], Field(max_length=20)]


@router.post("/exam-blueprints/validate")
def validate(tenant_id: UUID, body: BlueprintBody, actor: Actor, db: Db):
    access(db, tenant_id, actor, permission="exams.manage")
    sections, approved = load_blueprint(db, tenant_id, body)
    diagnostics = validate_blueprint(sections, approved)
    return {"valid": not diagnostics, "diagnostics": [asdict(item) for item in diagnostics]}


def load_blueprint(db, tenant_id, body):
    sections = tuple(
        Section(
            section.version_ids,
            section.minimum,
            section.maximum,
            tuple(CoverageRule(rule.term_id, rule.minimum, rule.maximum) for rule in section.coverage),
        )
        for section in body.sections
    )
    version_ids = {version_id for section in sections for version_id in section.version_ids}
    question_ids: dict[UUID, UUID] = {}
    terms: dict[UUID, set[UUID]] = {}
    if version_ids:
        query = (
            select(QuestionSelection.version_id, QuestionSelection.question_id, QuestionVersionTaxon.term_id)
            .outerjoin(
                QuestionVersionTaxon,
                and_(
                    QuestionVersionTaxon.tenant_id == QuestionSelection.tenant_id,
                    QuestionVersionTaxon.version_id == QuestionSelection.version_id,
                ),
            )
            .where(
                QuestionSelection.tenant_id == tenant_id,
                QuestionSelection.state == "approved",
                QuestionSelection.version_id.in_(version_ids),
            )
        )
        for version_id, question_id, term_id in db.execute(query):
            question_ids[version_id] = question_id
            if term_id is not None:
                terms.setdefault(version_id, set()).add(term_id)

    approved = {
        version_id: ApprovedSelection(question_id, frozenset(terms.get(version_id, ())))
        for version_id, question_id in question_ids.items()
    }
    return sections, approved


class SavedBlueprint(BlueprintBody):
    id: UUID
    exam_id: UUID
    revision: int
    parent_id: UUID | None


class DraftRevisionBody(BlueprintBody):
    id: UUID
    expected_revision: Annotated[int, Field(strict=True, ge=1, le=2147483646)]


def saved_blueprint(draft):
    return SavedBlueprint(
        id=draft.id,
        exam_id=draft.exam_id,
        revision=draft.revision,
        parent_id=draft.parent_id,
        **draft.blueprint,
    )


def latest_revision(db, tenant_id, exam_id):
    return db.scalar(
        select(func.max(ExamBlueprintDraft.revision)).where(
            ExamBlueprintDraft.tenant_id == tenant_id,
            ExamBlueprintDraft.exam_id == exam_id,
        )
    )


@router.get("/exam-blueprints/drafts/{draft_id}", response_model=SavedBlueprint)
def reopen_draft(tenant_id: UUID, draft_id: UUID, actor: Actor, db: Db):
    access(db, tenant_id, actor, permission="exams.manage")
    draft = db.get(ExamBlueprintDraft, (tenant_id, draft_id))
    if draft is None:
        reject(404, "blueprint_draft_not_found", "Blueprint draft not found")
    return saved_blueprint(draft)


@router.put("/exam-blueprints/drafts/{draft_id}", response_model=SavedBlueprint)
def save_draft(tenant_id: UUID, draft_id: UUID, body: BlueprintBody, actor: Actor, db: Db):
    access(db, tenant_id, actor, lock=True, permission="exams.manage")
    blueprint = body.model_dump(mode="json")
    draft = db.get(ExamBlueprintDraft, (tenant_id, draft_id))
    if draft is not None:
        if draft.blueprint != blueprint:
            reject(409, "blueprint_draft_conflict", "Draft ID already contains a different blueprint")
    else:
        db.execute(
            insert(ExamBlueprintDraft)
            .values(tenant_id=tenant_id, id=draft_id, exam_id=draft_id, revision=1, blueprint=blueprint)
            .on_conflict_do_nothing(index_elements=["tenant_id", "id"])
        )
        record(
            db,
            "exam.draft_created",
            actor=actor.user_id,
            tenant=tenant_id,
            subject=str(draft_id),
            before={},
            after={},
        )
    draft = db.get(ExamBlueprintDraft, (tenant_id, draft_id))
    response = saved_blueprint(draft)
    db.commit()
    return response


@router.post("/exam-blueprints/drafts/{draft_id}/revisions", response_model=SavedBlueprint)
def revise_draft(tenant_id: UUID, draft_id: UUID, body: DraftRevisionBody, actor: Actor, db: Db):
    access(db, tenant_id, actor, lock=True, permission="exams.manage")
    previous = db.get(ExamBlueprintDraft, (tenant_id, draft_id))
    if previous is None:
        reject(404, "blueprint_draft_not_found", "Blueprint draft not found")
    blueprint = BlueprintBody(sections=body.sections).model_dump(mode="json")
    existing = db.get(ExamBlueprintDraft, (tenant_id, body.id))
    if existing is not None:
        if (
            existing.exam_id != previous.exam_id
            or existing.parent_id != previous.id
            or existing.revision != body.expected_revision + 1
            or existing.blueprint != blueprint
        ):
            reject(409, "blueprint_draft_conflict", "Revision ID already contains a different draft")
        response = saved_blueprint(existing)
        db.commit()
        return response
    if (
        previous.revision != body.expected_revision
        or latest_revision(db, tenant_id, previous.exam_id) != previous.revision
    ):
        reject(409, "blueprint_revision_conflict", "Draft changed; reopen its latest revision")
    draft = ExamBlueprintDraft(
        tenant_id=tenant_id,
        id=body.id,
        exam_id=previous.exam_id,
        parent_id=previous.id,
        revision=previous.revision + 1,
        blueprint=blueprint,
    )
    db.add(draft)
    record(
        db,
        "exam.draft_revised",
        actor=actor.user_id,
        tenant=tenant_id,
        subject=str(draft.id),
        before={"revision": previous.revision},
        after={"revision": draft.revision},
    )
    response = saved_blueprint(draft)
    db.commit()
    return response


@router.get("/exam-blueprints/drafts/{draft_id}/history", response_model=list[SavedBlueprint])
def draft_history(tenant_id: UUID, draft_id: UUID, actor: Actor, db: Db):
    access(db, tenant_id, actor, permission="exams.manage")
    draft = db.get(ExamBlueprintDraft, (tenant_id, draft_id))
    if draft is None:
        reject(404, "blueprint_draft_not_found", "Blueprint draft not found")
    return [
        saved_blueprint(row)
        for row in db.scalars(
            select(ExamBlueprintDraft)
            .where(
                ExamBlueprintDraft.tenant_id == tenant_id,
                ExamBlueprintDraft.exam_id == draft.exam_id,
            )
            .order_by(ExamBlueprintDraft.revision)
        )
    ]


def publication_response(publication):
    snapshot = publication.snapshot
    return {
        "id": publication.id,
        "schema_version": snapshot["schema_version"],
        "policy": snapshot["policy"],
        "sections": [
            {
                **{key: section[key] for key in ("minimum", "maximum", "coverage")},
                "items": [
                    {
                        "version_id": item["version_id"],
                        **{
                            key: item["snapshot"][key]
                            for key in ("question_id", "title", "content", "taxonomy", "media")
                        },
                    }
                    for item in section["items"]
                ],
            }
            for section in snapshot["sections"]
        ],
    }


@router.get("/exam-blueprints/publications/{draft_id}")
def get_publication(tenant_id: UUID, draft_id: UUID, actor: Actor, db: Db):
    access(db, tenant_id, actor, permission="exams.manage")
    publication = db.get(ExamPublication, (tenant_id, draft_id))
    if publication is None:
        reject(404, "exam_publication_not_found", "Exam publication not found")
    return publication_response(publication)


@router.post("/exam-blueprints/drafts/{draft_id}/publish")
def publish_draft(
    tenant_id: UUID,
    draft_id: UUID,
    actor: Actor,
    db: Db,
    expected_revision: Annotated[int | None, Query(ge=1, le=2147483647)] = None,
):
    # Review and retirement acquire the same institution lock.
    access(db, tenant_id, actor, lock=True, permission="exams.manage")
    draft = db.get(ExamBlueprintDraft, (tenant_id, draft_id))
    if draft is None:
        reject(404, "blueprint_draft_not_found", "Blueprint draft not found")
    if expected_revision is not None and expected_revision != draft.revision:
        reject(409, "blueprint_revision_conflict", "Publication revision does not match the selected draft")
    publication = db.get(ExamPublication, (tenant_id, draft_id))
    if publication is not None:
        return publication_response(publication)
    if latest_revision(db, tenant_id, draft.exam_id) != draft.revision:
        reject(409, "blueprint_revision_conflict", "Only the current draft revision can be published")
    sections, approved = load_blueprint(db, tenant_id, BlueprintBody.model_validate(draft.blueprint))
    if validate_blueprint(sections, approved) or not approved:
        reject(409, "blueprint_not_publishable", "Blueprint is no longer eligible for publication")

    public_items = {}
    grading_references = {}
    for version_id in approved:
        selection = db.get(QuestionSelection, version_id)
        media = []
        storage = []
        for asset in version_assets(db, tenant_id, version_id):
            if asset.state != "clean":
                reject(409, "media_not_clean", "Media is not available for use")
            checked_bytes(db, asset)
            media.append(describe(asset, public=True))
            storage.append(
                {
                    "asset_id": str(asset.id),
                    "object_key": asset.object_key,
                    "object_version": asset.object_version,
                    "digest": asset.digest,
                    "byte_length": asset.byte_length,
                }
            )
        public_items[version_id] = {
            "question_id": str(selection.question_id),
            "title": selection.title,
            "content": selection.public_content,
            "taxonomy": taxonomy_snapshots(db, tenant_id, version_id),
            "media": media,
            "storage": storage,
        }
        grading_references[version_id] = {
            "version_id": str(version_id),
            "approval_event_id": str(selection.last_event_id),
        }

    snapshot = jsonable_encoder(build_snapshot(sections, approved, public_items, grading_references))
    publication = ExamPublication(tenant_id=tenant_id, id=draft_id, snapshot=snapshot)
    db.add(publication)
    record(db, "exam.published", actor=actor.user_id, tenant=tenant_id, subject=str(draft_id))
    response = publication_response(publication)
    db.commit()
    return response
