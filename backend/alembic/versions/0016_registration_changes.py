"""SCH-01/GOV-01 immutable registration changes and private decision reasons."""

from alembic import op

revision = "0016_registration_changes"
down_revision = "0015_sitting_cancellations"
branch_labels = None
depends_on = None


# Static DDL captured from this revision's model, never imported from future models.
TABLE_SQL = [
    "\nCREATE TABLE registration_changes (\n\ttenant_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tregistration_id UUID NOT NULL, \n\tsitting_id UUID NOT NULL, \n\tcandidate_user_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\taction VARCHAR(24) NOT NULL, \n\textra_minutes INTEGER NOT NULL, \n\tallowed_minutes INTEGER NOT NULL, \n\tcreated_by UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_registration_changes PRIMARY KEY (tenant_id, id), \n\tCONSTRAINT fk_change_registration FOREIGN KEY(tenant_id, registration_id) REFERENCES sitting_registrations (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_registration_change_revision UNIQUE (tenant_id, registration_id, revision), \n\tCONSTRAINT ck_registration_changes_change_revision CHECK (revision BETWEEN 2 AND 1000000), \n\tCONSTRAINT ck_registration_changes_change_action CHECK (action IN ('amend_accommodation', 'withdraw')), \n\tCONSTRAINT ck_registration_changes_change_duration CHECK (extra_minutes BETWEEN 0 AND 240 AND allowed_minutes BETWEEN 1 AND 1680), \n\tCONSTRAINT fk_registration_changes_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT\n)\n\n",
    "\nCREATE TABLE registration_change_reasons (\n\ttenant_id UUID NOT NULL, \n\tchange_id UUID NOT NULL, \n\treason VARCHAR(500) NOT NULL, \n\tCONSTRAINT pk_registration_change_reasons PRIMARY KEY (tenant_id, change_id), \n\tCONSTRAINT fk_change_reason FOREIGN KEY(tenant_id, change_id) REFERENCES registration_changes (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_registration_change_reasons_change_reason_length CHECK (length(trim(reason)) BETWEEN 3 AND 500)\n)\n\n",
]


def upgrade():
    for statement in TABLE_SQL:
        op.execute(statement)
    for table in ("registration_changes", "registration_change_reasons"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        staff = f"""tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid AND EXISTS (
            SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
            JOIN public.institutions i ON i.id=m.tenant_id
            WHERE m.tenant_id={table}.tenant_id
            AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid
            AND m.status='active' AND u.is_active AND i.status='active'
            AND m.role IN ('admin','coordinator'))"""
        read = staff
        if table == "registration_changes":
            read = f"""({staff}) OR (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid
                AND candidate_user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid
                AND EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
                JOIN public.institutions i ON i.id=m.tenant_id
                WHERE m.tenant_id=registration_changes.tenant_id AND m.user_id=registration_changes.candidate_user_id
                AND m.role='candidate' AND m.status='active' AND u.is_active AND i.status='active'))"""
            extra = "created_by=NULLIF(current_setting('app.actor_user_id',true),'')::uuid"
        else:
            extra = """EXISTS (SELECT 1 FROM public.registration_changes e
                WHERE e.tenant_id=registration_change_reasons.tenant_id
                AND e.id=registration_change_reasons.change_id
                AND e.created_by=NULLIF(current_setting('app.actor_user_id',true),'')::uuid)"""
        op.execute(f"CREATE POLICY {table}_read ON {table} FOR SELECT USING ({read})")
        op.execute(f"CREATE POLICY {table}_create ON {table} FOR INSERT WITH CHECK (({staff}) AND ({extra}))")
    op.execute("""
        CREATE FUNCTION registration_change_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        DECLARE original public.sitting_registrations%ROWTYPE;
                sitting public.exam_sittings%ROWTYPE;
                previous public.registration_changes%ROWTYPE;
                expected integer; current_extra integer; active_candidate boolean;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Registration changes are immutable' USING ERRCODE='42501';
            END IF;
            PERFORM 1 FROM public.institutions WHERE id=NEW.tenant_id FOR UPDATE;
            SELECT * INTO original FROM public.sitting_registrations
                WHERE tenant_id=NEW.tenant_id AND id=NEW.registration_id;
            SELECT * INTO sitting FROM public.exam_sittings
                WHERE tenant_id=NEW.tenant_id AND id=original.sitting_id;
            SELECT * INTO previous FROM public.registration_changes
                WHERE tenant_id=NEW.tenant_id AND registration_id=NEW.registration_id
                ORDER BY revision DESC LIMIT 1;
            expected := COALESCE(previous.revision,1)+1;
            current_extra := COALESCE(previous.extra_minutes,original.extra_minutes);
            IF original.id IS NULL OR sitting.id IS NULL OR NEW.revision IS DISTINCT FROM expected
                OR NEW.sitting_id IS DISTINCT FROM original.sitting_id
                OR NEW.candidate_user_id IS DISTINCT FROM original.candidate_user_id
                OR previous.action='withdraw' OR sitting.opens_at <= clock_timestamp()
                OR EXISTS (SELECT 1 FROM public.sitting_cancellations
                           WHERE tenant_id=NEW.tenant_id AND sitting_id=original.sitting_id)
                OR NEW.allowed_minutes IS DISTINCT FROM sitting.duration_minutes + NEW.extra_minutes
                OR sitting.closes_at < sitting.opens_at + NEW.allowed_minutes * interval '1 minute' THEN
                RAISE EXCEPTION 'Invalid registration transition or timing' USING ERRCODE='23514';
            END IF;
            IF NEW.action='withdraw' AND NEW.extra_minutes IS DISTINCT FROM current_extra THEN
                RAISE EXCEPTION 'Withdrawal must preserve the existing allowance' USING ERRCODE='23514';
            ELSIF NEW.action='amend_accommodation' THEN
                SELECT EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
                    WHERE m.tenant_id=NEW.tenant_id AND m.user_id=original.candidate_user_id
                    AND m.role='candidate' AND m.status='active' AND u.is_active) INTO active_candidate;
                IF NOT active_candidate OR NEW.extra_minutes IS NOT DISTINCT FROM current_extra THEN
                    RAISE EXCEPTION 'Unavailable candidate or unchanged allowance' USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION registration_change_reason_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Decision reasons are immutable' USING ERRCODE='42501';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION registration_change_reason_required() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM public.registration_change_reasons
                           WHERE tenant_id=NEW.tenant_id AND change_id=NEW.id) THEN
                RAISE EXCEPTION 'A private decision reason is required' USING ERRCODE='23514';
            END IF;
            RETURN NULL;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER registration_change_guard BEFORE INSERT OR UPDATE OR DELETE ON registration_changes FOR EACH ROW EXECUTE FUNCTION registration_change_guard()"
    )
    op.execute(
        "CREATE TRIGGER registration_change_reason_guard BEFORE INSERT OR UPDATE OR DELETE ON registration_change_reasons FOR EACH ROW EXECUTE FUNCTION registration_change_reason_guard()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER registration_change_reason_required AFTER INSERT ON registration_changes DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION registration_change_reason_required()"
    )


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM registration_changes) OR EXISTS (SELECT 1 FROM registration_change_reasons) THEN
                RAISE EXCEPTION 'Cannot discard registration decisions during downgrade';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER registration_change_reason_required ON registration_changes")
    op.execute("DROP TRIGGER registration_change_reason_guard ON registration_change_reasons")
    op.execute("DROP TRIGGER registration_change_guard ON registration_changes")
    op.execute("DROP FUNCTION registration_change_reason_required()")
    op.execute("DROP FUNCTION registration_change_reason_guard()")
    op.execute("DROP FUNCTION registration_change_guard()")
    op.drop_table("registration_change_reasons")
    op.drop_table("registration_changes")
