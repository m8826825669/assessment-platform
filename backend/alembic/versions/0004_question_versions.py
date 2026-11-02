"""Immutable tenant-owned question versions. QBK-01, TEN-01, PUB-01, IAM-01, GOV-01."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_question_versions"
down_revision = "0003_audit_outbox"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_questions"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_questions_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["institutions.id"],
            ondelete="RESTRICT",
            name="fk_questions_tenant_id_institutions",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_questions_created_by_users"
        ),
        sa.CheckConstraint("revision > 0", name=op.f("ck_questions_positive_revision")),
    )
    op.create_index("ix_questions_tenant_created", "questions", ["tenant_id", "created_at", "id"])
    op.create_table(
        "question_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("authored_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_question_versions"),
        sa.UniqueConstraint(
            "tenant_id", "question_id", "version_number", name="uq_question_versions_tenant_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "question_id"],
            ["questions.tenant_id", "questions.id"],
            ondelete="RESTRICT",
            name="fk_question_versions_tenant_id_questions",
        ),
        sa.ForeignKeyConstraint(
            ["authored_by"], ["users.id"], ondelete="RESTRICT", name="fk_question_versions_authored_by_users"
        ),
        sa.CheckConstraint("version_number > 0", name=op.f("ck_question_versions_positive_version")),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_question_versions_title_not_blank")),
        sa.CheckConstraint(
            "schema_version = 'question-content.v1'", name=op.f("ck_question_versions_schema_version")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content) = 'object'", name=op.f("ck_question_versions_content_object")
        ),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_question_versions_hash_format")),
    )
    op.create_foreign_key(
        "fk_questions_current_version",
        "questions",
        "question_versions",
        ["tenant_id", "id", "revision"],
        ["tenant_id", "question_id", "version_number"],
        deferrable=True,
        initially="DEFERRED",
    )
    # No SECURITY DEFINER or elevated function owner: these guards run as the caller.
    op.execute("""CREATE FUNCTION question_identity_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Question identity is retained' USING ERRCODE = '42501';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.created_by IS DISTINCT FROM OLD.created_by OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.revision::bigint <> OLD.revision::bigint + 1 THEN
                RAISE EXCEPTION 'Only the next revision is allowed' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER question_identity_guard BEFORE UPDATE OR DELETE ON questions FOR EACH ROW EXECUTE FUNCTION question_identity_guard()"
    )
    op.execute("""CREATE FUNCTION question_version_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        DECLARE current_revision integer;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Saved question versions are immutable' USING ERRCODE = '42501';
            END IF;
            SELECT q.revision INTO current_revision FROM public.questions q
                WHERE q.tenant_id = NEW.tenant_id AND q.id = NEW.question_id FOR UPDATE;
            IF current_revision IS NULL OR current_revision <> NEW.version_number THEN
                RAISE EXCEPTION 'Version must match the current revision' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER question_version_guard BEFORE INSERT OR UPDATE OR DELETE ON question_versions FOR EACH ROW EXECUTE FUNCTION question_version_guard()"
    )
    for table in ["questions", "question_versions"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    # Membership/user/institution rows are checked under the existing transaction-local context.
    scope = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    actor = "NULLIF(current_setting('app.actor_user_id', true), '')::uuid"
    authority = f"""EXISTS (SELECT 1 FROM public.memberships m
        JOIN public.institutions i ON i.id = m.tenant_id
        JOIN public.users u ON u.id = m.user_id
        WHERE m.tenant_id = questions.tenant_id AND m.user_id = {actor}
        AND m.status = 'active' AND i.status = 'active' AND u.is_active
        AND (m.role = 'admin' OR (m.role = 'author' AND questions.created_by = {actor})))"""
    permitted = f"({scope}) AND ({authority})"
    op.execute(f"CREATE POLICY question_read ON questions FOR SELECT USING ({permitted})")
    op.execute(
        f"CREATE POLICY question_create ON questions FOR INSERT WITH CHECK (({permitted}) AND created_by = {actor} AND revision = 1)"
    )
    op.execute(
        f"CREATE POLICY question_revise ON questions FOR UPDATE USING ({permitted}) WITH CHECK ({permitted})"
    )
    version_scope = f"""({scope}) AND EXISTS (SELECT 1 FROM public.questions q
        WHERE q.tenant_id = question_versions.tenant_id AND q.id = question_versions.question_id)"""
    op.execute(f"CREATE POLICY question_version_read ON question_versions FOR SELECT USING ({version_scope})")
    op.execute(
        f"CREATE POLICY question_version_append ON question_versions FOR INSERT WITH CHECK (({version_scope}) AND authored_by = {actor})"
    )
    # Runtime gets INSERT/SELECT and revision-only UPDATE by explicit operator grant refresh.


def downgrade():
    # Destructive development operation, never an automatic production rollback.
    op.drop_constraint("fk_questions_current_version", "questions", type_="foreignkey")
    op.drop_table("question_versions")
    op.drop_index("ix_questions_tenant_created", table_name="questions")
    op.drop_table("questions")
    op.execute("DROP FUNCTION question_version_guard()")
    op.execute("DROP FUNCTION question_identity_guard()")
