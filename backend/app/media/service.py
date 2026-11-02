"""Atomic media state/audit mutations; external uploads may leave inaccessible orphans."""

from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import service as audit
from app.db.models import MediaAsset, QuestionVersionMedia
from app.identity.service import reject
from app.media.adapters import InvalidImage, MediaUnavailable, inspect_image
from app.question_bank import service as questions


def gateway(db):
    value = db.info.get("media")
    if value is None:
        reject(503, "media_unavailable", "Media service unavailable")
    return value


def find(db, tenant, identifier):
    value = db.scalar(
        select(MediaAsset)
        .where(MediaAsset.tenant_id == tenant, MediaAsset.id == identifier)
        .execution_options(populate_existing=True)
    )
    if value is None:
        reject(404, "media_not_found", "Media not found")
    return value


def authority(db, tenant, actor, identifier=None, *, mutate=False):
    member = questions.authority(
        db, tenant, actor, lock=mutate, permission="questions.write" if mutate else "taxonomy.read"
    )
    asset = find(db, tenant, identifier) if identifier else None
    if asset and mutate and member.role != "admin" and asset.created_by != actor.user_id:
        reject(404, "media_not_found", "Media not found")
    return asset


def state(asset):
    return {"asset_id": str(asset.id), "media_revision": asset.revision, "media_state": asset.state}


def describe(asset, *, public=False):
    result = {
        "asset_id": asset.id,
        "mime_type": asset.mime_type,
        "description": asset.description,
        "width": asset.width,
        "height": asset.height,
    }
    if not public:
        result.update(
            filename=asset.filename,
            state=asset.state,
            revision=asset.revision,
            byte_length=asset.byte_length,
            error_code=asset.error_code,
        )
    return result


def details(db, tenant, actor, identifier):
    member = questions.authority(db, tenant, actor, permission="taxonomy.read")
    asset = find(db, tenant, identifier)
    public = member.role != "admin" and not (member.role == "author" and asset.created_by == actor.user_id)
    return describe(asset, public=public)


def commit(db, asset, action, actor, before=None):
    db.flush()
    audit.record(db, action, actor.user_id, asset.tenant_id, str(asset.id), before=before, after=state(asset))
    result = describe(asset)
    db.commit()
    return result


def reserve(db, tenant, actor, body):
    authority(db, tenant, actor, mutate=True)
    gateway(db)
    extensions = {"image/png": (".png",), "image/jpeg": (".jpg", ".jpeg")}
    if not body.filename.lower().endswith(extensions[body.mime_type]):
        reject(422, "media_invalid", "Invalid media input")
    asset = MediaAsset(
        id=uuid4(),
        tenant_id=tenant,
        created_by=actor.user_id,
        filename=body.filename,
        mime_type=body.mime_type,
        description=body.description,
        state="pending",
        revision=1,
    )
    db.add(asset)
    return commit(db, asset, "media.reserved", actor)


def preflight(db, tenant, actor, identifier):
    member = questions.authority(db, tenant, actor)
    asset = find(db, tenant, identifier)
    if member.role != "admin" and asset.created_by != actor.user_id:
        reject(404, "media_not_found", "Media not found")
    gateway(db)
    db.rollback()  # No institution lock or open read transaction while receiving the request body.


def upload(db, tenant, actor, identifier, expected_revision, mime, data):
    asset = authority(db, tenant, actor, identifier, mutate=True)
    adapter = gateway(db)
    if asset.state != "pending" or asset.revision != expected_revision:
        reject(409, "media_conflict", "Media changed; reload before retrying")
    if mime != asset.mime_type:
        reject(422, "media_invalid", "Invalid media input")
    try:
        width, height = inspect_image(data, mime)
    except InvalidImage:
        reject(422, "media_invalid", "Invalid media input")
    before = state(asset)
    # New random key per attempt: a failed SQL commit never overwrites an existing reference.
    key = f"authoring/{tenant}/{uuid4().hex}"
    try:
        version = adapter.store.put(key, data, mime)
        digest = sha256(data).hexdigest()
        adapter.store.get(key, version, digest, len(data))  # Verify stored exact version before recording it.
    except MediaUnavailable:
        reject(503, "media_unavailable", "Media service unavailable")
    asset.object_key, asset.object_version, asset.digest = key, version, digest
    asset.byte_length, asset.width, asset.height = len(data), width, height
    asset.state = "quarantine"
    asset.revision += 1
    return commit(db, asset, "media.uploaded", actor, before)


def checked_bytes(db, asset):
    try:
        data = gateway(db).store.get(asset.object_key, asset.object_version, asset.digest, asset.byte_length)
        inspect_image(data, asset.mime_type)
        return data
    except (MediaUnavailable, InvalidImage):
        reject(503, "media_unavailable", "Media service unavailable")


def scan(db, tenant, actor, identifier, expected_revision):
    asset = authority(db, tenant, actor, identifier, mutate=True)
    adapter = gateway(db)
    if asset.state != "quarantine" or asset.revision != expected_revision:
        reject(409, "media_conflict", "Media changed; reload before retrying")
    before = state(asset)
    data = checked_bytes(db, asset)
    try:
        verdict, version = adapter.scanner.scan(data)
        if verdict not in {"clean", "rejected"}:
            raise MediaUnavailable()
        asset.state, asset.scanner_version, asset.error_code = verdict, version, None
    except MediaUnavailable:
        asset.error_code = "scan_unavailable"
    asset.revision += 1
    return commit(db, asset, "media.scanned", actor, before)


def download(db, tenant, actor, identifier):
    asset = authority(db, tenant, actor, identifier)
    if asset.state != "clean":
        reject(409, "media_not_clean", "Media is not available for use")
    return asset.mime_type, checked_bytes(db, asset)


def validate_references(db, tenant, actor, ids):
    if not ids:
        return []
    gateway(db)
    member = questions.authority(db, tenant, actor)
    assets = []
    for identifier in ids:
        asset = find(db, tenant, identifier)
        if member.role != "admin" and asset.created_by != actor.user_id:
            reject(404, "media_not_found", "Media not found")
        if asset.state != "clean":
            reject(409, "media_not_clean", "Media is not available for use")
        checked_bytes(db, asset)
        assets.append(asset)
    return assets


def capture(db, row, saved, actor, ids):
    for asset in validate_references(db, row.tenant_id, actor, ids):
        db.add(
            QuestionVersionMedia(
                tenant_id=row.tenant_id, question_id=row.id, version_id=saved.id, asset_id=asset.id
            )
        )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        reject(409, "media_conflict", "Media changed; reload before retrying")


def snapshots(db, tenant, version_id, *, verify=False):
    assets = db.scalars(
        select(MediaAsset)
        .join(
            QuestionVersionMedia,
            (QuestionVersionMedia.tenant_id == MediaAsset.tenant_id)
            & (QuestionVersionMedia.asset_id == MediaAsset.id),
        )
        .where(QuestionVersionMedia.tenant_id == tenant, QuestionVersionMedia.version_id == version_id)
        .order_by(MediaAsset.id)
    )
    result = []
    for asset in assets:
        if asset.state != "clean":
            reject(409, "media_not_clean", "Media is not available for use")
        if verify:
            checked_bytes(db, asset)
        result.append(describe(asset, public=True))
    return result
