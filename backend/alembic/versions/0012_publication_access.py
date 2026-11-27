"""Restore coordinator public-only question access."""

from alembic import op

revision = "0012_publication_access"
down_revision = "0011_publication_grading"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP POLICY question_version_publication_read ON question_versions")


def downgrade():
    # Restore the previous schema, including its broader access.
    op.execute(
        "\n        CREATE POLICY question_version_publication_read ON question_versions FOR SELECT USING (\n            current_setting('app.publication_read', true) = 'on'\n            AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid\n            AND EXISTS (\n                SELECT 1 FROM public.memberships m\n                JOIN public.users u ON u.id = m.user_id\n                JOIN public.institutions i ON i.id = m.tenant_id\n                WHERE m.tenant_id = question_versions.tenant_id\n                  AND m.user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid\n                  AND m.role IN ('admin', 'coordinator') AND m.status = 'active'\n                  AND u.is_active AND i.status = 'active'\n            )\n            AND EXISTS (\n                SELECT 1 FROM public.question_selections s\n                WHERE s.tenant_id = question_versions.tenant_id\n                  AND s.question_id = question_versions.question_id\n                  AND s.version_id = question_versions.id AND s.state = 'approved'\n            )\n        )\n    "
    )
