from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Institution(Base):
    __tablename__ = "institutions"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("status IN ('active', 'suspended')", name="status_values"),
        UniqueConstraint("slug"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """Global identity; credentials are never serialized in API responses."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(trim(email)) AND length(email) > 3", name="email_normalized"),
        CheckConstraint("length(trim(display_name)) > 0", name="name_not_blank"),
        UniqueConstraint("email"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    """Tenant-scoped membership; evaluated on every protected request."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint("status IN ('active', 'suspended')", name="status_values"),
        CheckConstraint(
            "role IN ('admin', 'coordinator', 'author', 'reviewer', 'invigilator', 'examiner', 'candidate')",
            name="role_values",
        ),
        Index("ix_memberships_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("institutions.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, server_default="candidate")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_format"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        Index("ix_auth_sessions_user_id", "user_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginBucket(Base):
    __tablename__ = "login_buckets"
    __table_args__ = (CheckConstraint("attempts > 0", name="positive_attempts"),)
    bucket_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)


class SecurityEvent(Base):
    """Minimal append-only security history; general audit/outbox is P1-004."""

    __tablename__ = "security_events"
    __table_args__ = (Index("ix_security_events_tenant_id", "tenant_id"), {"implicit_returning": False})
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditRecord(Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        UniqueConstraint("id", "scope_key"),
        CheckConstraint("scope_key = COALESCE(tenant_id::text, 'global')", name="scope_matches_tenant"),
        CheckConstraint(
            "jsonb_typeof(before_state) = 'object' AND jsonb_typeof(after_state) = 'object'",
            name="state_objects",
        ),
        CheckConstraint("actor_kind IN ('user', 'operator', 'anonymous')", name="actor_kind_values"),
        Index("ix_audit_records_tenant_created", "tenant_id", "created_at", "id"),
        {"implicit_returning": False},
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    scope_key: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    before_state: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    after_state: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    request_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("audit_id"),
        ForeignKeyConstraint(
            ["audit_id", "scope_key"], ["audit_records.id", "audit_records.scope_key"], ondelete="RESTRICT"
        ),
        CheckConstraint("scope_key = COALESCE(tenant_id::text, 'global')", name="scope_matches_tenant"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        {"implicit_returning": False},
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    audit_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    scope_key: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxDelivery(Base):
    __tablename__ = "outbox_deliveries"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processing', 'delivered', 'dead')", name="status_values"),
        CheckConstraint(
            "max_attempts BETWEEN 1 AND 20 AND attempts BETWEEN 0 AND max_attempts", name="attempt_bounds"
        ),
        CheckConstraint(
            "(status = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="lease_matches_status",
        ),
        CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)", name="delivery_matches_status"
        ),
        Index("ix_outbox_deliveries_ready", "status", "available_at"),
        {"implicit_returning": False},
    )
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("outbox_events.id", ondelete="RESTRICT"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class ConsumerReceipt(Base):
    __tablename__ = "consumer_receipts"
    __table_args__ = (CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="hash_format"),)
    consumer: Mapped[str] = mapped_column(String(80), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("outbox_events.id", ondelete="RESTRICT"), primary_key=True
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Question(Base):
    """Stable ownership and a fenced pointer to the latest immutable saved draft."""

    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("revision > 0", name="positive_revision"),
        ForeignKeyConstraint(
            ["tenant_id", "id", "revision"],
            [
                "question_versions.tenant_id",
                "question_versions.question_id",
                "question_versions.version_number",
            ],
            name="fk_questions_current_version",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_questions_tenant_created", "tenant_id", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("institutions.id", ondelete="RESTRICT"))
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionVersion(Base):
    __tablename__ = "question_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "question_id", "version_number"),
        UniqueConstraint(
            "tenant_id", "question_id", "id", "content_hash", name="uq_question_versions_review_binding"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "question_id"], ["questions.tenant_id", "questions.id"], ondelete="RESTRICT"
        ),
        CheckConstraint("version_number > 0", name="positive_version"),
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
        CheckConstraint("schema_version = 'question-content.v1'", name="schema_version"),
        CheckConstraint("jsonb_typeof(content) = 'object'", name="content_object"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="hash_format"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    question_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authored_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionReviewEvent(Base):
    """Append-only decisions; the last sequence is the exact version's workflow state."""

    __tablename__ = "question_review_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version_id", "sequence"),
        UniqueConstraint("tenant_id", "question_id", "version_id", "id", name="uq_review_selection_binding"),
        ForeignKeyConstraint(
            ["tenant_id", "question_id", "version_id", "content_hash"],
            [
                "question_versions.tenant_id",
                "question_versions.question_id",
                "question_versions.id",
                "question_versions.content_hash",
            ],
            ondelete="RESTRICT",
            name="fk_review_version_binding",
        ),
        CheckConstraint("sequence > 0 AND expected_revision > 0", name="positive_revisions"),
        CheckConstraint(
            "(action, state) IN (('submit','in_review'),('return','returned'),('approve','approved'),('retire','retired'),('supersede','superseded'))",
            name="action_state",
        ),
        CheckConstraint(
            "(action IN ('return','retire') AND reason IS NOT NULL AND length(trim(reason)) BETWEEN 1 AND 1000) OR (action NOT IN ('return','retire') AND reason IS NULL)",
            name="reason_required",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    question_id: Mapped[UUID] = mapped_column(Uuid)
    version_id: Mapped[UUID] = mapped_column(Uuid)
    content_hash: Mapped[str] = mapped_column(String(64))
    originating_author: Mapped[UUID] = mapped_column(Uuid)
    actor_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    sequence: Mapped[int] = mapped_column(Integer)
    expected_revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionSelection(Base):
    """Contains only public approved content; coordinators never need private version access."""

    __tablename__ = "question_selections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "question_id", "version_id", "last_event_id"],
            [
                "question_review_events.tenant_id",
                "question_review_events.question_id",
                "question_review_events.version_id",
                "question_review_events.id",
            ],
            ondelete="RESTRICT",
            name="fk_selection_review",
        ),
        CheckConstraint("state IN ('approved', 'retired')", name="state_values"),
        CheckConstraint("jsonb_typeof(public_content) = 'object'", name="public_object"),
        Index("ix_question_selections_tenant_version", "tenant_id", "version_id"),
    )
    version_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    question_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200))
    public_content: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(20))
    last_event_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
