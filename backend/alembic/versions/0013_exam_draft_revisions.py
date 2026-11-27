"""ASM-01/PUB-01 immutable exam draft lineage with stale-write protection."""

import sqlalchemy as sa

from alembic import op

revision = "0013_exam_draft_revisions"
down_revision = "0012_publication_access"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("exam_blueprint_drafts", sa.Column("exam_id", sa.Uuid(), nullable=True))
    op.add_column(
        "exam_blueprint_drafts", sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("exam_blueprint_drafts", sa.Column("parent_id", sa.Uuid(), nullable=True))
    # Backfill as table owner even when the migration login does not bypass forced RLS.
    # These DDL changes and the backfill are atomic in the migration transaction.
    op.execute("ALTER TABLE exam_blueprint_drafts NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE exam_blueprint_drafts SET exam_id=id")
    op.execute("ALTER TABLE exam_blueprint_drafts FORCE ROW LEVEL SECURITY")
    op.alter_column("exam_blueprint_drafts", "exam_id", nullable=False)
    op.create_unique_constraint(
        "uq_exam_draft_revision", "exam_blueprint_drafts", ["tenant_id", "exam_id", "revision"]
    )
    op.create_foreign_key(
        "fk_exam_draft_root",
        "exam_blueprint_drafts",
        "exam_blueprint_drafts",
        ["tenant_id", "exam_id"],
        ["tenant_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_exam_draft_parent",
        "exam_blueprint_drafts",
        "exam_blueprint_drafts",
        ["tenant_id", "parent_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint("draft_revision_positive", "exam_blueprint_drafts", "revision >= 1")
    op.create_check_constraint(
        "draft_lineage",
        "exam_blueprint_drafts",
        "(revision = 1 AND parent_id IS NULL AND exam_id = id) OR (revision > 1 AND parent_id IS NOT NULL)",
    )
    op.execute("""
        CREATE FUNCTION exam_draft_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        DECLARE previous public.exam_blueprint_drafts%ROWTYPE; latest integer;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Draft revisions are immutable' USING ERRCODE='42501';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text || NEW.exam_id::text, 0));
            SELECT max(revision) INTO latest FROM public.exam_blueprint_drafts
                WHERE tenant_id=NEW.tenant_id AND exam_id=NEW.exam_id;
            IF NEW.revision = 1 THEN
                IF NEW.id IS DISTINCT FROM NEW.exam_id OR NEW.parent_id IS NOT NULL OR latest IS NOT NULL THEN
                    RAISE EXCEPTION 'Invalid draft root' USING ERRCODE='23514';
                END IF;
            ELSE
                SELECT * INTO previous FROM public.exam_blueprint_drafts
                    WHERE tenant_id=NEW.tenant_id AND id=NEW.parent_id;
                IF previous.id IS NULL OR previous.exam_id IS DISTINCT FROM NEW.exam_id
                    OR previous.revision IS DISTINCT FROM latest OR NEW.revision <> latest + 1 THEN
                    RAISE EXCEPTION 'Draft parent is not current' USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER exam_draft_guard BEFORE INSERT OR UPDATE OR DELETE ON exam_blueprint_drafts
        FOR EACH ROW EXECUTE FUNCTION exam_draft_guard()
    """)


def downgrade():
    # A downgrade cannot discard actual revision history without an explicit migration design.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM exam_blueprint_drafts WHERE revision > 1) THEN
                RAISE EXCEPTION 'Cannot downgrade while exam draft revisions exist';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER exam_draft_guard ON exam_blueprint_drafts")
    op.execute("DROP FUNCTION exam_draft_guard()")
    op.drop_constraint(op.f("ck_exam_blueprint_drafts_draft_lineage"), "exam_blueprint_drafts", type_="check")
    op.drop_constraint(
        op.f("ck_exam_blueprint_drafts_draft_revision_positive"), "exam_blueprint_drafts", type_="check"
    )
    op.drop_constraint("fk_exam_draft_parent", "exam_blueprint_drafts", type_="foreignkey")
    op.drop_constraint("fk_exam_draft_root", "exam_blueprint_drafts", type_="foreignkey")
    op.drop_constraint("uq_exam_draft_revision", "exam_blueprint_drafts", type_="unique")
    op.drop_column("exam_blueprint_drafts", "parent_id")
    op.drop_column("exam_blueprint_drafts", "revision")
    op.drop_column("exam_blueprint_drafts", "exam_id")
