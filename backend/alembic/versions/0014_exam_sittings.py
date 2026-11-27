"""SCH-01/TEN-01 immutable sittings and candidate timing snapshots."""

from alembic import op

revision = "0014_exam_sittings"
down_revision = "0013_exam_draft_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE exam_sittings (\n\ttenant_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tpublication_id UUID NOT NULL, \n\ttitle VARCHAR(160) NOT NULL, \n\topens_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcloses_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdisplay_timezone VARCHAR(9) NOT NULL, \n\tduration_minutes INTEGER NOT NULL, \n\tpolicy JSONB NOT NULL, \n\tcreated_by UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_exam_sittings PRIMARY KEY (tenant_id, id), \n\tCONSTRAINT fk_sitting_publication FOREIGN KEY(tenant_id, publication_id) REFERENCES exam_publications (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_exam_sittings_sitting_title CHECK (length(trim(title)) BETWEEN 1 AND 160), \n\tCONSTRAINT ck_exam_sittings_sitting_duration CHECK (duration_minutes BETWEEN 1 AND 1440), \n\tCONSTRAINT ck_exam_sittings_sitting_window CHECK (closes_at >= opens_at + duration_minutes * interval '1 minute'), \n\tCONSTRAINT ck_exam_sittings_sitting_timezone CHECK (display_timezone ~ '^UTC([+-]((0[0-9]|1[0-3]):[0-5][0-9]|14:00))?$'), \n\tCONSTRAINT fk_exam_sittings_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE sitting_registrations (\n\ttenant_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tsitting_id UUID NOT NULL, \n\tcandidate_user_id UUID NOT NULL, \n\textra_minutes INTEGER NOT NULL, \n\tallowed_minutes INTEGER NOT NULL, \n\taccommodation_reason VARCHAR(500), \n\tcreated_by UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_sitting_registrations PRIMARY KEY (tenant_id, id), \n\tCONSTRAINT fk_registration_sitting FOREIGN KEY(tenant_id, sitting_id) REFERENCES exam_sittings (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_registration_candidate FOREIGN KEY(tenant_id, candidate_user_id) REFERENCES memberships (tenant_id, user_id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_sitting_candidate UNIQUE (tenant_id, sitting_id, candidate_user_id), \n\tCONSTRAINT ck_sitting_registrations_registration_duration CHECK (extra_minutes BETWEEN 0 AND 240 AND allowed_minutes BETWEEN 1 AND 1680), \n\tCONSTRAINT ck_sitting_registrations_registration_reason CHECK ((extra_minutes=0 AND accommodation_reason IS NULL) OR (extra_minutes>0 AND length(trim(accommodation_reason)) BETWEEN 3 AND 500 AND accommodation_reason IS NOT NULL)), \n\tCONSTRAINT fk_sitting_registrations_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute("ALTER TABLE exam_sittings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE exam_sittings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY exam_sittings_read ON exam_sittings FOR SELECT USING ((tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid) AND ((EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id\n JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=exam_sittings.tenant_id AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid\n AND m.status='active' AND u.is_active AND i.status='active' AND m.role IN ('admin','coordinator'))) OR (EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id\n JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=exam_sittings.tenant_id AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid\n AND m.status='active' AND u.is_active AND i.status='active' AND m.role='candidate') AND EXISTS (SELECT 1 FROM public.sitting_registrations r WHERE r.tenant_id=exam_sittings.tenant_id AND r.sitting_id=exam_sittings.id AND r.candidate_user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid))))"
    )
    op.execute(
        "CREATE POLICY exam_sittings_create ON exam_sittings FOR INSERT WITH CHECK ((tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid) AND (EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id\n JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=exam_sittings.tenant_id AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid\n AND m.status='active' AND u.is_active AND i.status='active' AND m.role IN ('admin','coordinator'))) AND created_by=NULLIF(current_setting('app.actor_user_id',true),'')::uuid)"
    )
    op.execute("ALTER TABLE sitting_registrations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sitting_registrations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY sitting_registrations_read ON sitting_registrations FOR SELECT USING ((tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid) AND ((EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id\n JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=sitting_registrations.tenant_id AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid\n AND m.status='active' AND u.is_active AND i.status='active' AND m.role IN ('admin','coordinator'))) OR (EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id\n JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=sitting_registrations.tenant_id AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid\n AND m.status='active' AND u.is_active AND i.status='active' AND m.role='candidate') AND candidate_user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid)))"
    )
    op.execute(
        "CREATE POLICY sitting_registrations_create ON sitting_registrations FOR INSERT WITH CHECK ((tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid) AND (EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id\n JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=sitting_registrations.tenant_id AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid\n AND m.status='active' AND u.is_active AND i.status='active' AND m.role IN ('admin','coordinator'))) AND created_by=NULLIF(current_setting('app.actor_user_id',true),'')::uuid)"
    )
    op.execute("""
        CREATE FUNCTION sitting_snapshot_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        DECLARE expected jsonb; sitting public.exam_sittings%ROWTYPE; active_candidate boolean;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Sitting and registration snapshots are immutable' USING ERRCODE='42501';
            END IF;
            PERFORM 1 FROM public.institutions WHERE id=NEW.tenant_id FOR UPDATE;
            IF TG_TABLE_NAME='exam_sittings' THEN
                SELECT snapshot->'policy' INTO expected FROM public.exam_publications
                    WHERE tenant_id=NEW.tenant_id AND id=NEW.publication_id;
                IF expected IS NULL OR NEW.policy IS DISTINCT FROM expected
                    OR NEW.duration_minutes IS DISTINCT FROM (expected->>'duration_minutes')::integer
                    OR NEW.opens_at <= clock_timestamp() THEN
                    RAISE EXCEPTION 'Invalid sitting publication or timing policy' USING ERRCODE='23514';
                END IF;
            ELSE
                SELECT * INTO sitting FROM public.exam_sittings WHERE tenant_id=NEW.tenant_id AND id=NEW.sitting_id;
                SELECT EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
                    WHERE m.tenant_id=NEW.tenant_id AND m.user_id=NEW.candidate_user_id
                    AND m.role='candidate' AND m.status='active' AND u.is_active) INTO active_candidate;
                IF sitting.id IS NULL OR NOT active_candidate OR sitting.opens_at <= clock_timestamp()
                    OR NEW.allowed_minutes IS DISTINCT FROM sitting.duration_minutes + NEW.extra_minutes
                    OR sitting.closes_at < sitting.opens_at + NEW.allowed_minutes * interval '1 minute' THEN
                    RAISE EXCEPTION 'Invalid candidate registration or accommodation' USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER exam_sitting_guard BEFORE INSERT OR UPDATE OR DELETE ON exam_sittings "
        "FOR EACH ROW EXECUTE FUNCTION sitting_snapshot_guard()"
    )
    op.execute(
        "CREATE TRIGGER sitting_registration_guard BEFORE INSERT OR UPDATE OR DELETE ON sitting_registrations "
        "FOR EACH ROW EXECUTE FUNCTION sitting_snapshot_guard()"
    )


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM exam_sittings) OR EXISTS (SELECT 1 FROM sitting_registrations) THEN
                RAISE EXCEPTION 'Cannot discard existing sittings or registrations during downgrade';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER sitting_registration_guard ON sitting_registrations")
    op.execute("DROP TRIGGER exam_sitting_guard ON exam_sittings")
    op.execute("DROP FUNCTION sitting_snapshot_guard()")
    op.execute("DROP POLICY exam_sittings_read ON exam_sittings")
    op.drop_table("sitting_registrations")
    op.drop_table("exam_sittings")
