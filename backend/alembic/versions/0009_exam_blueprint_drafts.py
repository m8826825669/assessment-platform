"""Persist tenant-scoped fixed exam blueprint drafts."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0009_exam_blueprint_drafts"
down_revision = "0008_question_imports"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "exam_blueprint_drafts",
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("institutions.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("blueprint", JSONB(), nullable=False),
    )
    op.execute("ALTER TABLE exam_blueprint_drafts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE exam_blueprint_drafts FORCE ROW LEVEL SECURITY")
    scope = """tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        AND EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
            JOIN public.institutions i ON i.id=m.tenant_id
            WHERE m.tenant_id=exam_blueprint_drafts.tenant_id
            AND m.user_id=NULLIF(current_setting('app.actor_user_id', true), '')::uuid
            AND m.role IN ('admin','coordinator') AND m.status='active'
            AND i.status='active' AND u.is_active)"""
    op.execute(f"CREATE POLICY blueprint_draft_read ON exam_blueprint_drafts FOR SELECT USING ({scope})")
    op.execute(
        f"CREATE POLICY blueprint_draft_create ON exam_blueprint_drafts FOR INSERT WITH CHECK ({scope})"
    )


def downgrade():
    op.drop_table("exam_blueprint_drafts")
