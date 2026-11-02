"""P2-002: authorized append-only saved drafts; review/approval remains P2-003."""

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.db.models import AuthSession, Question, QuestionVersion, User
from app.identity.service import Principal, reject, tenant_membership
from app.question_bank.contracts import Content, candidate_view, content_hash, validate_content

SCHEMA_VERSION = "question-content.v1"


def authority(
    db: Session, tenant: UUID, actor: Principal, *, lock: bool = False, permission: str = "questions.write"
):
    member = tenant_membership(db, tenant, actor, permission, lock=lock)
    # Authentication may have waited for the institution lock; recheck live session/user now.
    valid = db.scalar(
        select(AuthSession.id)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.id == actor.session_id,
            AuthSession.user_id == actor.user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > func.clock_timestamp(),
            User.is_active.is_(True),
        )
    )
    if valid is None:
        reject(401, "invalid_session", "Authentication required")
    return member


def question(db, tenant, actor, identifier, *, lock=False):
    member = authority(db, tenant, actor, lock=lock)
    query = select(Question).where(Question.tenant_id == tenant, Question.id == identifier)
    if member.role != "admin":
        query = query.where(Question.created_by == actor.user_id)
    if lock:
        query = query.with_for_update()
    row = db.scalar(query.execution_options(populate_existing=True))
    if row is None:
        reject(404, "question_not_found", "Question not found")
    return row


def version(db, row, version_id=None):
    query = select(QuestionVersion).where(
        QuestionVersion.tenant_id == row.tenant_id,
        QuestionVersion.question_id == row.id,
    )
    query = (
        query.where(QuestionVersion.id == version_id)
        if version_id
        else query.where(QuestionVersion.version_number == row.revision)
    )
    saved = db.scalar(query)
    if saved is None:
        reject(404, "question_not_found", "Question not found")
    return saved


def audit_state(saved):
    return {"version_id": str(saved.id), "revision": saved.version_number, "content_hash": saved.content_hash}


def metadata(saved, db=None):
    from app.question_bank import review

    workflow = review.status(db, saved) if db is not None else {"state": "draft", "review_revision": 0}
    return {
        "question_id": saved.question_id,
        "version_id": saved.id,
        "version_number": saved.version_number,
        "title": saved.title,
        "schema_version": saved.schema_version,
        "content_hash": saved.content_hash,
        "authored_by": saved.authored_by,
        "created_at": saved.created_at,
        **workflow,
    }


def detail(row, saved, db=None):
    return {
        **metadata(saved, db=db),
        "tenant_id": row.tenant_id,
        "created_by": row.created_by,
        "revision": row.revision,
        "content": saved.content,
    }


def append_version(db, row, actor, title, content: Content):
    saved = QuestionVersion(
        id=uuid4(),
        tenant_id=row.tenant_id,
        question_id=row.id,
        version_number=row.revision,
        title=title,
        schema_version=SCHEMA_VERSION,
        content=content.model_dump(mode="json"),
        content_hash=content_hash(content),
        authored_by=actor.user_id,
    )
    db.add(saved)
    db.flush()
    return saved


def create(db, tenant, actor, title, content):
    authority(db, tenant, actor, lock=True)
    row = Question(id=uuid4(), tenant_id=tenant, created_by=actor.user_id, revision=1)
    try:
        db.add(row)
        db.flush()  # Current-version FK is deferred until both rows and audit commit.
        saved = append_version(db, row, actor, title, content)
        audit.record(db, "question.created", actor.user_id, tenant, str(row.id), after=audit_state(saved))
        db.commit()
    except IntegrityError:
        db.rollback()
        reject(409, "question_conflict", "Question write conflicted; reload before retrying")
    return detail(row, saved)


def revise(db, tenant, actor, identifier, expected_revision, title, content):
    row = question(db, tenant, actor, identifier, lock=True)
    if row.revision != expected_revision:
        reject(409, "question_conflict", "Question write conflicted; reload before retrying")
    previous = version(db, row)
    try:
        from app.question_bank.review import supersede_pending

        supersede_pending(db, row, previous, actor)
        row.revision += 1
        db.flush()
        saved = append_version(db, row, actor, title, content)
        audit.record(
            db,
            "question.revised",
            actor.user_id,
            tenant,
            str(row.id),
            before=audit_state(previous),
            after=audit_state(saved),
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        reject(409, "question_conflict", "Question write conflicted; reload before retrying")
    return detail(row, saved)


def get(db, tenant, actor, identifier, version_id=None):
    row = question(db, tenant, actor, identifier)
    return detail(row, version(db, row, version_id), db=db)


def history(db, tenant, actor, identifier, offset, limit):
    row = question(db, tenant, actor, identifier)
    rows = db.scalars(
        select(QuestionVersion)
        .where(
            QuestionVersion.tenant_id == tenant,
            QuestionVersion.question_id == row.id,
        )
        .order_by(QuestionVersion.version_number.desc())
        .offset(offset)
        .limit(limit)
    )
    return [metadata(saved, db=db) for saved in rows]


def listing(db, tenant, actor, offset, limit):
    member = authority(db, tenant, actor)
    query = (
        select(QuestionVersion)
        .join(
            Question,
            (
                (Question.tenant_id == QuestionVersion.tenant_id)
                & (Question.id == QuestionVersion.question_id)
                & (Question.revision == QuestionVersion.version_number)
            ),
        )
        .where(Question.tenant_id == tenant)
    )
    if member.role != "admin":
        query = query.where(Question.created_by == actor.user_id)
    return [
        metadata(saved, db=db)
        for saved in db.scalars(query.order_by(Question.created_at, Question.id).offset(offset).limit(limit))
    ]


def preview(db, tenant, actor, identifier, version_id=None):
    row = question(db, tenant, actor, identifier)
    saved = version(db, row, version_id)
    # Never serialize the staff detail here. The hash and every key/rubric stay private.
    return {
        "question_id": row.id,
        "version_id": saved.id,
        "content": candidate_view(validate_content(saved.content)),
    }
