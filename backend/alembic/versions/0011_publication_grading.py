"""Allow publication transactions to read exact approved grading sources."""

from alembic import op

revision = "0011_publication_grading"
down_revision = "0010_exam_publications"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE POLICY question_version_publication_read ON question_versions FOR SELECT USING (
            current_setting('app.publication_read', true) = 'on'
            AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            AND EXISTS (
                SELECT 1 FROM public.memberships m
                JOIN public.users u ON u.id = m.user_id
                JOIN public.institutions i ON i.id = m.tenant_id
                WHERE m.tenant_id = question_versions.tenant_id
                  AND m.user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
                  AND m.role IN ('admin', 'coordinator') AND m.status = 'active'
                  AND u.is_active AND i.status = 'active'
            )
            AND EXISTS (
                SELECT 1 FROM public.question_selections s
                WHERE s.tenant_id = question_versions.tenant_id
                  AND s.question_id = question_versions.question_id
                  AND s.version_id = question_versions.id AND s.state = 'approved'
            )
        )
    """)


def downgrade():
    op.execute("DROP POLICY question_version_publication_read ON question_versions")
