"""Institution, global identity and tenant membership foundation.

Requirement references: TEN-01, OPS-01. This migration does not implement RLS or authentication.
"""

import sqlalchemy as sa

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "institutions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_institutions"),
        sa.UniqueConstraint("slug", name="uq_institutions_slug"),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_institutions_slug_format")),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_institutions_name_not_blank")),
        sa.CheckConstraint("status IN ('active', 'suspended')", name=op.f("ck_institutions_status_values")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "email = lower(trim(email)) AND length(email) > 3", name=op.f("ck_users_email_normalized")
        ),
        sa.CheckConstraint("length(trim(display_name)) > 0", name=op.f("ck_users_name_not_blank")),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["institutions.id"],
            ondelete="RESTRICT",
            name="fk_memberships_tenant_id_institutions",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_memberships_user_id_users"
        ),
        sa.CheckConstraint("status IN ('active', 'suspended')", name=op.f("ck_memberships_status_values")),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])


def downgrade() -> None:
    # Destructive: only for disposable local databases, never an automated production rollback.
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("institutions")
