"""P2-003: append-only review decisions and public approved selection."""

from uuid import uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError

from app.audit import service as audit
from app.db.models import Question, QuestionReviewEvent, QuestionSelection, QuestionVersion
from app.identity.service import reject, tenant_membership
from app.question_bank import service
from app.question_bank.contracts import candidate_view, validate_content

TRANSITIONS = {
    ("draft", "submit"): "in_review",
    ("in_review", "return"): "returned",
    ("in_review", "approve"): "approved",
    ("in_review", "supersede"): "superseded",
    ("approved", "retire"): "retired",
}
ACTIONS = {
    "submit": "submitted",
    "return": "returned",
    "approve": "approved",
    "retire": "retired",
    "supersede": "superseded",
}


def transition(state, action):
    if (state, action) not in TRANSITIONS:
        raise ValueError("Invalid review transition")
    return TRANSITIONS[state, action]


def latest(db, saved):
    return db.scalar(
        select(QuestionReviewEvent)
        .where(
            QuestionReviewEvent.tenant_id == saved.tenant_id,
            QuestionReviewEvent.version_id == saved.id,
        )
        .order_by(QuestionReviewEvent.sequence.desc())
        .limit(1)
    )


def status(db, saved):
    previous = latest(db, saved)
    return {
        "state": previous.state if previous else "draft",
        "review_revision": previous.sequence if previous else 0,
    }


def audit_state(saved, previous):
    return {
        **service.audit_state(saved),
        "review_state": previous.state if previous else "draft",
        "review_revision": previous.sequence if previous else 0,
    }


def append(db, row, saved, actor, action, previous, reason=None):
    event = QuestionReviewEvent(
        id=uuid4(),
        tenant_id=row.tenant_id,
        question_id=row.id,
        version_id=saved.id,
        content_hash=saved.content_hash,
        originating_author=row.created_by,
        actor_user_id=actor.user_id,
        sequence=previous.sequence + 1 if previous else 1,
        expected_revision=row.revision,
        action=action,
        state=transition(previous.state if previous else "draft", action),
        reason=reason,
    )
    db.add(event)
    db.flush()
    audit.record(
        db,
        "question.review_" + ACTIONS[action],
        actor.user_id,
        row.tenant_id,
        str(row.id),
        before=audit_state(saved, previous),
        after=audit_state(saved, event),
    )
    return event


def supersede_pending(db, row, saved, actor):
    previous = latest(db, saved)
    if previous and previous.state == "in_review":
        append(db, row, saved, actor, "supersede", previous)


def access(db, tenant, actor, *, lock=False, permission="questions.review"):
    return service.authority(db, tenant, actor, lock=lock, permission=permission)


def binding(db, tenant, question_id, version_id):
    row = db.scalar(
        select(Question)
        .where(Question.tenant_id == tenant, Question.id == question_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        reject(404, "question_not_found", "Question not found")
    saved = service.version(db, row, version_id)
    return row, saved


def decide(db, tenant, actor, question_id, version_id, body):
    access(
        db,
        tenant,
        actor,
        lock=True,
        permission="questions.write" if body.action == "submit" else "questions.review",
    )
    row, saved = binding(db, tenant, question_id, version_id)
    previous = latest(db, saved)
    sequence = previous.sequence if previous else 0
    if (
        body.expected_revision != row.revision
        or body.expected_review_revision != sequence
        or body.content_hash != saved.content_hash
    ):
        reject(409, "review_conflict", "Review state changed; reload before retrying")
    if body.action != "retire" and saved.version_number != row.revision:
        reject(409, "review_conflict", "Review state changed; reload before retrying")
    if body.action in {"approve", "return"} and actor.user_id in {
        row.created_by,
        saved.authored_by,
        previous.actor_user_id if previous else None,
    }:
        reject(403, "review_self", "An independent reviewer is required")
    try:
        transition(previous.state if previous else "draft", body.action)
    except ValueError:
        reject(409, "review_conflict", "Review state changed; reload before retrying")
    if body.action in {"submit", "approve"}:
        from app.media.service import snapshots as media_snapshots

        media_snapshots(db, tenant, saved.id, verify=True)
    try:
        event = append(db, row, saved, actor, body.action, previous, body.reason)
        if body.action == "approve":
            db.add(
                QuestionSelection(
                    version_id=saved.id,
                    tenant_id=tenant,
                    question_id=row.id,
                    title=saved.title,
                    public_content=candidate_view(validate_content(saved.content)),
                    state="approved",
                    last_event_id=event.id,
                )
            )
        elif body.action == "retire":
            selected = db.get(QuestionSelection, saved.id)
            if selected is None:
                reject(409, "review_conflict", "Review state changed; reload before retrying")
            selected.state, selected.last_event_id = "retired", event.id
        db.flush()
        result = service.detail(row, saved, db=db)
        db.commit()
    except IntegrityError:
        db.rollback()
        reject(409, "review_conflict", "Review state changed; reload before retrying")
    return result


def detail(db, tenant, actor, question_id, version_id, offset=0, limit=100):
    # Authors may read their own feedback; reviewers may read versions submitted for review.
    member = tenant_membership(db, tenant, actor)
    permission = "questions.write" if member.role == "author" else "questions.review"
    access(db, tenant, actor, permission=permission)
    row, saved = binding(db, tenant, question_id, version_id)
    events = db.scalars(
        select(QuestionReviewEvent)
        .where(
            QuestionReviewEvent.tenant_id == tenant,
            QuestionReviewEvent.version_id == saved.id,
        )
        .order_by(QuestionReviewEvent.sequence.desc())
        .offset(offset)
        .limit(limit)
    )
    return {
        **service.detail(row, saved, db=db),
        "decisions": [
            {
                "id": event.id,
                "sequence": event.sequence,
                "action": event.action,
                "state": event.state,
                "actor_user_id": event.actor_user_id,
                "reason": event.reason,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


def queue(db, tenant, actor, offset, limit, filters=None):
    access(db, tenant, actor)
    current = (
        select(QuestionReviewEvent.version_id, func.max(QuestionReviewEvent.sequence).label("sequence"))
        .where(QuestionReviewEvent.tenant_id == tenant)
        .group_by(QuestionReviewEvent.version_id)
        .subquery()
    )
    query = (
        select(QuestionVersion)
        .join(
            QuestionReviewEvent,
            and_(
                QuestionReviewEvent.tenant_id == QuestionVersion.tenant_id,
                QuestionReviewEvent.version_id == QuestionVersion.id,
            ),
        )
        .join(
            current,
            and_(
                current.c.version_id == QuestionReviewEvent.version_id,
                current.c.sequence == QuestionReviewEvent.sequence,
            ),
        )
        .where(QuestionVersion.tenant_id == tenant, QuestionReviewEvent.state == "in_review")
        .order_by(QuestionReviewEvent.created_at, QuestionReviewEvent.id)
    )
    from app.question_bank.taxonomy import apply_filters

    query = apply_filters(db, tenant, query, QuestionVersion, filters, queue=True)
    rows = db.scalars(query.offset(offset).limit(limit))
    return [service.metadata(saved, db=db) for saved in rows]


def selections(db, tenant, actor, offset, limit, version_id=None, filters=None):
    access(db, tenant, actor, permission="exams.manage")
    query = select(QuestionSelection).where(
        QuestionSelection.tenant_id == tenant, QuestionSelection.state == "approved"
    )
    if version_id:
        query = query.where(QuestionSelection.version_id == version_id)
    from app.media.service import snapshots as media_snapshots
    from app.question_bank.taxonomy import apply_filters, snapshots

    query = apply_filters(db, tenant, query, QuestionSelection, filters, public=True)
    rows = list(
        db.scalars(
            query.order_by(QuestionSelection.created_at, QuestionSelection.version_id)
            .offset(offset)
            .limit(limit)
        )
    )
    if version_id and not rows:
        reject(404, "question_not_found", "Question not found")
    return [
        {
            "question_id": row.question_id,
            "version_id": row.version_id,
            "title": row.title,
            "content": row.public_content,
            "taxonomy": snapshots(db, tenant, row.version_id),
            "media": media_snapshots(db, tenant, row.version_id, verify=True),
        }
        for row in rows
    ]
