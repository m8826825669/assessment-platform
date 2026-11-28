"""SCH-01/TEN-01 preview and atomic commit of bounded CSV registrations."""

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from app.identity.api import Actor, Db
from app.identity.service import reject
from app.question_bank.review import access
from app.scheduling.api import (
    RegistrationBatch,
    get_sitting,
    persist_registration_batch,
    plan_registration_batch,
    registration_status,
)
from assessment_core.registration_csv import MAX_BYTES, RegistrationCsvError, parse_registration_csv

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}", tags=["exam sittings"])
BODY_DOCS = {
    "requestBody": {
        "required": True,
        "content": {"text/csv": {"schema": {"type": "string", "maxLength": MAX_BYTES}}},
    }
}
PLAN_CODES = frozenset(
    {
        "registration_conflict",
        "candidate_unavailable",
        "accommodation_window_too_short",
        "sitting_cancelled",
        "registration_closed",
    }
)


def preflight(db, tenant_id, sitting_id, actor):
    access(db, tenant_id, actor, permission="exams.manage")
    get_sitting(db, tenant_id, sitting_id)
    db.rollback()  # Release authorization/read transaction before consuming the stream.


async def document(request, db, tenant_id, sitting_id, actor):
    await run_in_threadpool(preflight, db, tenant_id, sitting_id, actor)
    if request.query_params:
        reject(422, "registration_csv_invalid", "Invalid CSV request")
    media = [part.strip().lower() for part in request.headers.get("content-type", "").split(";")]
    if (
        len(request.headers.getlist("content-type")) != 1
        or media[0] != "text/csv"
        or (len(media) > 1 and media[1:] not in (["charset=utf-8"], ['charset="utf-8"']))
    ):
        reject(415, "registration_csv_media_type", "Use UTF-8 text/csv")
    lengths = request.headers.getlist("content-length")
    if len(lengths) > 1 or (
        lengths
        and (
            len(lengths[0]) > 10
            or not lengths[0].isascii()
            or not lengths[0].isdecimal()
            or int(lengths[0]) > MAX_BYTES
        )
    ):
        reject(413, "registration_csv_too_large", "CSV exceeds the size limit")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BYTES:
            reject(413, "registration_csv_too_large", "CSV exceeds the size limit")
        data.extend(chunk)
    return bytes(data)


def preview_document(db, tenant_id, sitting_id, actor, data):
    access(db, tenant_id, actor, permission="exams.manage")
    get_sitting(db, tenant_id, sitting_id)
    try:
        parsed = parse_registration_csv(data)
    except RegistrationCsvError as error:
        return {
            "valid": False,
            "row_count": None,
            "new_count": 0,
            "replayed_count": 0,
            "rows": [],
            "diagnostics": [asdict(error.diagnostic)],
        }
    batch = RegistrationBatch(registrations=parsed)
    rows, diagnostics = [], []
    for index, candidate in enumerate(batch.registrations, start=2):
        try:
            pending, result = plan_registration_batch(
                db, tenant_id, sitting_id, RegistrationBatch(registrations=[candidate]), actor
            )
        except HTTPException as error:
            code = error.detail.get("code") if isinstance(error.detail, dict) else None
            if code not in PLAN_CODES:
                raise
            diagnostics.append({"row": index, "column": None, "code": code})
            continue
        effective = (
            registration_status(db, result[0])
            if not pending
            else {"revision": 1, "status": "active", "allowed_minutes": result[0].allowed_minutes}
        )
        rows.append(
            {
                "row": index,
                "status": "new" if pending else "replayed",
                "allowed_minutes": result[0].allowed_minutes,
                "registration_status": effective["status"],
                "registration_revision": effective["revision"],
                "effective_allowed_minutes": effective["allowed_minutes"],
            }
        )
    return {
        "valid": not diagnostics,
        "row_count": len(parsed),
        "new_count": sum(row["status"] == "new" for row in rows),
        "replayed_count": sum(row["status"] == "replayed" for row in rows),
        "rows": rows,
        "diagnostics": diagnostics,
    }


def commit_document(db, tenant_id, sitting_id, actor, data):
    access(db, tenant_id, actor, lock=True, permission="exams.manage")
    try:
        body = RegistrationBatch(registrations=parse_registration_csv(data))
    except RegistrationCsvError as error:
        issue = error.diagnostic
        raise RequestValidationError(
            [
                {
                    "loc": ("body", issue.row or 0, issue.column or "csv"),
                    "type": issue.code,
                    "msg": "Invalid CSV input",
                }
            ]
        ) from None
    pending, result = plan_registration_batch(db, tenant_id, sitting_id, body, actor)
    return persist_registration_batch(db, tenant_id, actor, pending, result)


@router.post("/exam-sittings/{sitting_id}/registrations/csv/preview", openapi_extra=BODY_DOCS)
async def preview(tenant_id: UUID, sitting_id: UUID, request: Request, actor: Actor, db: Db):
    data = await document(request, db, tenant_id, sitting_id, actor)
    return await run_in_threadpool(preview_document, db, tenant_id, sitting_id, actor, data)


@router.post("/exam-sittings/{sitting_id}/registrations/csv", openapi_extra=BODY_DOCS)
async def commit(tenant_id: UUID, sitting_id: UUID, request: Request, actor: Actor, db: Db):
    data = await document(request, db, tenant_id, sitting_id, actor)
    return await run_in_threadpool(commit_document, db, tenant_id, sitting_id, actor, data)
