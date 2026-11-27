"""Persist tenant-scoped immutable exam publications."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0010_exam_publications"
down_revision = "0009_exam_blueprint_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "exam_publications",
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "id"],
            ["exam_blueprint_drafts.tenant_id", "exam_blueprint_drafts.id"],
            name="fk_exam_publication_draft",
            ondelete="RESTRICT",
        ),
    )
    op.execute("ALTER TABLE exam_publications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE exam_publications FORCE ROW LEVEL SECURITY")
    scope = """tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        AND EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
            JOIN public.institutions i ON i.id=m.tenant_id
            WHERE m.tenant_id=exam_publications.tenant_id
            AND m.user_id=NULLIF(current_setting('app.actor_user_id', true), '')::uuid
            AND m.role IN ('admin','coordinator') AND m.status='active'
            AND i.status='active' AND u.is_active)"""
    op.execute(f"CREATE POLICY exam_publication_read ON exam_publications FOR SELECT USING ({scope})")
    op.execute(f"CREATE POLICY exam_publication_create ON exam_publications FOR INSERT WITH CHECK ({scope})")


def downgrade():
    op.drop_table("exam_publications")
