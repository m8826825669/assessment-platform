"""Single transaction import using the normal draft and reference validation paths."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import service as audit
from app.db.models import QuestionImportReceipt
from app.identity.service import reject
from app.media import service as media
from app.question_bank import service as questions
from app.question_bank import taxonomy
from app.question_bank.contracts import candidate_view
from app.question_imports.contracts import PROFILE, fingerprint


def preview(db, tenant, actor, body):
    questions.authority(db, tenant, actor)
    rows = []
    for index, item in enumerate(body.items):
        terms = taxonomy.classification_terms(db, tenant, item.taxonomy_ids)
        assets = media.validate_references(db, tenant, actor, item.media_ids)
        rows.append(
            {
                "index": index,
                "reference": item.reference,
                "title": item.title,
                "taxonomy_count": len(terms),
                "media_count": len(assets),
                "preview": candidate_view(item.content),
            }
        )
    questions.authority(db, tenant, actor)  # Live authority again after storage reads.
    return {"schema_version": PROFILE, "valid": True, "item_count": len(rows), "items": rows}


def reply(receipt):
    return {
        "batch_id": receipt.id,
        "schema_version": receipt.profile,
        "created_at": receipt.created_at,
        "created_as": "draft",
        "item_count": receipt.item_count,
        "items": receipt.result,
    }


def commit(db, tenant, actor, body, key):
    questions.authority(db, tenant, actor, lock=True)
    digest = fingerprint(body)
    receipt = db.scalar(
        select(QuestionImportReceipt).where(
            QuestionImportReceipt.tenant_id == tenant,
            QuestionImportReceipt.actor_user_id == actor.user_id,
            QuestionImportReceipt.idempotency_key == key,
        )
    )
    if receipt is not None:
        if receipt.request_hash != digest:
            reject(409, "import_conflict", "Import key was used for a different document")
        result = reply(receipt)
        db.commit()  # Release the authorization lock; replay performs no business/audit writes.
        return result, True
    try:
        result = []
        for item in body.items:
            row, saved = questions.stage_create(
                db, tenant, actor, item.title, item.content, item.taxonomy_ids, item.media_ids
            )
            result.append(
                {"reference": item.reference, "question_id": str(row.id), "version_id": str(saved.id)}
            )
        receipt = QuestionImportReceipt(
            id=uuid4(),
            tenant_id=tenant,
            actor_user_id=actor.user_id,
            idempotency_key=key,
            profile=PROFILE,
            request_hash=digest,
            item_count=len(result),
            result=result,
        )
        db.add(receipt)
        db.flush()
        audit.record(
            db,
            "question.import_committed",
            actor.user_id,
            tenant,
            str(receipt.id),
            after={"batch_id": str(receipt.id), "item_count": len(result)},
        )
        questions.authority(db, tenant, actor)  # Expired/revoked session never leaves a partial batch.
        response = reply(receipt)
        db.commit()
    except IntegrityError:
        db.rollback()
        reject(409, "import_conflict", "Import key was used for a different document")
    except Exception:
        db.rollback()
        raise
    return response, False


def get(db, tenant, actor, identifier):
    questions.authority(db, tenant, actor)
    receipt = db.scalar(
        select(QuestionImportReceipt).where(
            QuestionImportReceipt.tenant_id == tenant,
            QuestionImportReceipt.actor_user_id == actor.user_id,
            QuestionImportReceipt.id == identifier,
        )
    )
    if receipt is None:
        reject(404, "import_not_found", "Import receipt not found")
    return reply(receipt)
