"""Independent immutable question review and safe approved selections. QBK-01, IAM-01, GOV-01."""

from alembic import op

revision = "0005_question_review"
down_revision = "0004_question_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_question_versions_review_binding",
        "question_versions",
        ["tenant_id", "question_id", "id", "content_hash"],
    )
    op.execute(
        "CREATE TABLE question_review_events (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tquestion_id UUID NOT NULL, \n\tversion_id UUID NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\toriginating_author UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\tsequence INTEGER NOT NULL, \n\texpected_revision INTEGER NOT NULL, \n\taction VARCHAR(20) NOT NULL, \n\tstate VARCHAR(20) NOT NULL, \n\treason VARCHAR(1000), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_question_review_events PRIMARY KEY (id), \n\tCONSTRAINT uq_question_review_events_tenant_id UNIQUE (tenant_id, version_id, sequence), \n\tCONSTRAINT uq_review_selection_binding UNIQUE (tenant_id, question_id, version_id, id), \n\tCONSTRAINT fk_review_version_binding FOREIGN KEY(tenant_id, question_id, version_id, content_hash) REFERENCES question_versions (tenant_id, question_id, id, content_hash) ON DELETE RESTRICT, \n\tCONSTRAINT ck_question_review_events_positive_revisions CHECK (sequence > 0 AND expected_revision > 0), \n\tCONSTRAINT ck_question_review_events_action_state CHECK ((action, state) IN (('submit','in_review'),('return','returned'),('approve','approved'),('retire','retired'),('supersede','superseded'))), \n\tCONSTRAINT ck_question_review_events_reason_required CHECK ((action IN ('return','retire') AND reason IS NOT NULL AND length(trim(reason)) BETWEEN 1 AND 1000) OR (action NOT IN ('return','retire') AND reason IS NULL)), \n\tCONSTRAINT fk_question_review_events_actor_user_id_users FOREIGN KEY(actor_user_id) REFERENCES users (id) ON DELETE RESTRICT\n)"
    )
    op.execute(
        "CREATE TABLE question_selections (\n\tversion_id UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tquestion_id UUID NOT NULL, \n\ttitle VARCHAR(200) NOT NULL, \n\tpublic_content JSONB NOT NULL, \n\tstate VARCHAR(20) NOT NULL, \n\tlast_event_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_question_selections PRIMARY KEY (version_id), \n\tCONSTRAINT fk_selection_review FOREIGN KEY(tenant_id, question_id, version_id, last_event_id) REFERENCES question_review_events (tenant_id, question_id, version_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_question_selections_state_values CHECK (state IN ('approved', 'retired')), \n\tCONSTRAINT ck_question_selections_public_object CHECK (jsonb_typeof(public_content) = 'object')\n)"
    )
    op.execute(
        "CREATE INDEX ix_question_selections_tenant_version ON question_selections (tenant_id, version_id)"
    )
    for table in ["question_review_events", "question_selections"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    actor = "NULLIF(current_setting('app.actor_user_id', true), '')::uuid"
    scope = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    # Event visibility depends on its immutable origin column, never on question/version policies.
    # This keeps reviewer visibility free of recursive RLS dependencies.
    active = f"""EXISTS (SELECT 1 FROM public.memberships m JOIN public.institutions i ON i.id=m.tenant_id
        JOIN public.users u ON u.id=m.user_id WHERE m.tenant_id=question_review_events.tenant_id
        AND m.user_id={actor} AND m.status='active' AND i.status='active' AND u.is_active
        AND (m.role IN ('admin','reviewer') OR (m.role='author' AND originating_author={actor})))"""
    op.execute(
        f"CREATE POLICY review_read ON question_review_events FOR SELECT USING (({scope}) AND ({active}))"
    )
    op.execute(
        f"CREATE POLICY review_append ON question_review_events FOR INSERT WITH CHECK (({scope}) AND ({active}) AND actor_user_id={actor})"
    )
    op.execute(f"""CREATE POLICY reviewer_question_read ON questions FOR SELECT USING (
        ({scope}) AND EXISTS (SELECT 1 FROM public.question_review_events e
            WHERE e.tenant_id=questions.tenant_id AND e.question_id=questions.id AND e.action='submit')
    )""")
    # Replace the broad parent-based version policy: seeing one submitted version must not reveal later drafts.
    op.execute("DROP POLICY question_version_read ON question_versions")
    author = f"""EXISTS (SELECT 1 FROM public.questions q JOIN public.memberships m ON m.tenant_id=q.tenant_id
        WHERE q.id=question_versions.question_id AND q.tenant_id=question_versions.tenant_id
        AND m.user_id={actor} AND m.status='active'
        AND (m.role='admin' OR (m.role='author' AND q.created_by={actor})))"""
    submitted = "EXISTS (SELECT 1 FROM public.question_review_events e WHERE e.tenant_id=question_versions.tenant_id AND e.version_id=question_versions.id AND e.action='submit')"
    op.execute(
        f"CREATE POLICY question_version_read ON question_versions FOR SELECT USING (({scope}) AND (({author}) OR ({submitted})))"
    )
    # Appending versions remains an authoring operation, not a side effect of reviewer visibility.
    op.execute("DROP POLICY question_version_append ON question_versions")
    op.execute(
        f"CREATE POLICY question_version_append ON question_versions FOR INSERT WITH CHECK (({scope}) AND ({author}) AND authored_by={actor})"
    )
    selection_authority = f"""EXISTS (SELECT 1 FROM public.memberships m JOIN public.institutions i ON i.id=m.tenant_id
        JOIN public.users u ON u.id=m.user_id WHERE m.tenant_id=question_selections.tenant_id AND m.user_id={actor}
        AND m.status='active' AND i.status='active' AND u.is_active AND (m.role IN ('admin','reviewer') OR (m.role='coordinator' AND question_selections.state='approved')))"""
    selection_writer = selection_authority.replace(
        "(m.role IN ('admin','reviewer') OR (m.role='coordinator' AND question_selections.state='approved'))",
        "m.role IN ('admin','reviewer')",
    )
    op.execute(
        f"CREATE POLICY selection_read ON question_selections FOR SELECT USING (({scope}) AND ({selection_authority}))"
    )
    op.execute(
        f"CREATE POLICY selection_append ON question_selections FOR INSERT WITH CHECK (({scope}) AND ({selection_writer}))"
    )
    op.execute(
        f"CREATE POLICY selection_retire ON question_selections FOR UPDATE USING (({scope}) AND ({selection_writer})) WITH CHECK (({scope}) AND ({selection_writer}))"
    )
    # Root revision updates and review events share a transaction advisory lock. No definer privileges.
    op.execute("""CREATE OR REPLACE FUNCTION question_identity_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Question identity is retained' USING ERRCODE='42501'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(OLD.tenant_id::text || OLD.id::text, 0));
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.created_by IS DISTINCT FROM OLD.created_by OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.revision::bigint <> OLD.revision::bigint + 1 THEN
                RAISE EXCEPTION 'Only the next revision is allowed' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute("""CREATE FUNCTION question_review_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        DECLARE q public.questions%ROWTYPE; v public.question_versions%ROWTYPE;
                previous public.question_review_events%ROWTYPE; role_name text; actor uuid;
        BEGIN
            IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Review decisions are immutable' USING ERRCODE='42501'; END IF;
            actor := NULLIF(current_setting('app.actor_user_id', true), '')::uuid;
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text || NEW.question_id::text, 0));
            SELECT * INTO q FROM public.questions WHERE tenant_id=NEW.tenant_id AND id=NEW.question_id;
            SELECT * INTO v FROM public.question_versions WHERE tenant_id=NEW.tenant_id AND question_id=NEW.question_id AND id=NEW.version_id;
            IF q.id IS NULL OR v.id IS NULL OR q.created_by IS DISTINCT FROM NEW.originating_author
               OR v.content_hash IS DISTINCT FROM NEW.content_hash OR actor IS DISTINCT FROM NEW.actor_user_id THEN
                RAISE EXCEPTION 'Review binding mismatch' USING ERRCODE='23514';
            END IF;
            SELECT m.role INTO role_name FROM public.memberships m JOIN public.institutions i ON i.id=m.tenant_id
                JOIN public.users u ON u.id=m.user_id WHERE m.tenant_id=NEW.tenant_id AND m.user_id=actor
                AND m.status='active' AND i.status='active' AND u.is_active;
            SELECT * INTO previous FROM public.question_review_events WHERE tenant_id=NEW.tenant_id AND version_id=NEW.version_id ORDER BY sequence DESC LIMIT 1;
            IF NEW.expected_revision <> q.revision OR NEW.sequence <> COALESCE(previous.sequence,0)+1 THEN
                RAISE EXCEPTION 'Stale review' USING ERRCODE='23514';
            END IF;
            IF NEW.action <> 'retire' AND v.version_number <> q.revision THEN
                RAISE EXCEPTION 'Only the current version may be reviewed' USING ERRCODE='23514';
            END IF;
            IF NEW.action IN ('submit','supersede') THEN
                IF role_name IS NULL OR NOT (role_name='admin' OR (role_name='author' AND q.created_by=actor)) THEN
                    RAISE EXCEPTION 'Authoring permission required' USING ERRCODE='42501'; END IF;
            ELSE
                IF role_name IS NULL OR role_name NOT IN ('admin','reviewer') THEN
                    RAISE EXCEPTION 'Review permission required' USING ERRCODE='42501'; END IF;
            END IF;
            IF NEW.action IN ('approve','return') AND (actor=q.created_by OR actor=v.authored_by OR actor=previous.actor_user_id) THEN
                RAISE EXCEPTION 'Independent reviewer required' USING ERRCODE='42501'; END IF;
            IF NOT COALESCE((
                (NEW.action='submit' AND COALESCE(previous.state,'draft')='draft') OR
                (NEW.action IN ('approve','return','supersede') AND previous.state='in_review') OR
                (NEW.action='retire' AND previous.state='approved')
            ), false) THEN RAISE EXCEPTION 'Invalid review transition' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER question_review_guard BEFORE INSERT OR UPDATE OR DELETE ON question_review_events FOR EACH ROW EXECUTE FUNCTION question_review_guard()"
    )
    op.execute("""CREATE FUNCTION question_public_content(c jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE STRICT
        SET search_path = pg_catalog, public AS $$
        DECLARE result jsonb; values_json jsonb;
        BEGIN
            result := jsonb_build_object('kind',c->'kind','item_id',c->'item_id','prompt',c->'prompt','points',c->'points');
            CASE c->>'kind'
                WHEN 'single_choice', 'multiple_select' THEN
                    SELECT jsonb_agg(jsonb_build_object('id',x->'id','text',x->'text') ORDER BY n) INTO values_json
                        FROM jsonb_array_elements(c->'options') WITH ORDINALITY AS a(x,n);
                    result := result || jsonb_build_object('options',values_json);
                WHEN 'numeric' THEN result := result || jsonb_build_object('unit_label',c->'unit_label');
                WHEN 'short_answer', 'essay' THEN result := result || jsonb_build_object('max_response_characters',c->'max_response_characters');
                WHEN 'file_upload' THEN result := result || jsonb_build_object('allowed_extensions',c->'allowed_extensions','max_files',c->'max_files','max_bytes_per_file',c->'max_bytes_per_file');
                WHEN 'passage_group' THEN
                    SELECT jsonb_agg(public.question_public_content(x) ORDER BY n) INTO values_json FROM jsonb_array_elements(c->'children') WITH ORDINALITY AS a(x,n);
                    result := result || jsonb_build_object('passage',c->'passage','children',values_json);
                ELSE RAISE EXCEPTION 'Unknown content kind' USING ERRCODE='23514';
            END CASE;
            RETURN result;
        END $$""")
    op.execute("""CREATE FUNCTION question_selection_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        DECLARE latest public.question_review_events%ROWTYPE; v public.question_versions%ROWTYPE;
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Selection history is retained' USING ERRCODE='42501'; END IF;
            SELECT * INTO latest FROM public.question_review_events WHERE tenant_id=NEW.tenant_id AND version_id=NEW.version_id ORDER BY sequence DESC LIMIT 1;
            IF latest.id IS NULL OR latest.id IS DISTINCT FROM NEW.last_event_id OR latest.question_id IS DISTINCT FROM NEW.question_id OR latest.state IS DISTINCT FROM NEW.state THEN
                RAISE EXCEPTION 'Selection must match latest review decision' USING ERRCODE='23514'; END IF;
            IF TG_OP='INSERT' THEN
                IF latest.state <> 'approved' THEN RAISE EXCEPTION 'Approval required' USING ERRCODE='23514'; END IF;
                SELECT * INTO v FROM public.question_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.version_id;
                NEW.title := v.title;
                NEW.public_content := public.question_public_content(v.content);
            ELSE
                IF OLD.state <> 'approved' OR NEW.state <> 'retired' OR NEW.version_id IS DISTINCT FROM OLD.version_id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                   OR NEW.question_id IS DISTINCT FROM OLD.question_id OR NEW.title IS DISTINCT FROM OLD.title OR NEW.public_content IS DISTINCT FROM OLD.public_content OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'Only retirement is allowed' USING ERRCODE='23514'; END IF;
            END IF;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER question_selection_guard BEFORE INSERT OR UPDATE OR DELETE ON question_selections FOR EACH ROW EXECUTE FUNCTION question_selection_guard()"
    )

    op.execute("""CREATE FUNCTION question_review_projection_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        DECLARE latest public.question_review_events%ROWTYPE;
        BEGIN
            IF NEW.action NOT IN ('approve','retire') THEN RETURN NEW; END IF;
            SELECT * INTO latest FROM public.question_review_events WHERE tenant_id=NEW.tenant_id AND version_id=NEW.version_id ORDER BY sequence DESC LIMIT 1;
            IF NOT EXISTS (SELECT 1 FROM public.question_selections s WHERE s.tenant_id=latest.tenant_id
                AND s.question_id=latest.question_id AND s.version_id=latest.version_id
                AND s.last_event_id=latest.id AND s.state=latest.state) THEN
                RAISE EXCEPTION 'Review and selection must commit together' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE CONSTRAINT TRIGGER question_review_projection_guard AFTER INSERT ON question_review_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION question_review_projection_guard()"
    )


def downgrade():
    op.execute("DROP POLICY reviewer_question_read ON questions")
    op.execute("DROP POLICY question_version_read ON question_versions")
    op.execute("DROP POLICY question_version_append ON question_versions")
    op.execute("DROP TRIGGER question_review_projection_guard ON question_review_events")
    op.execute("DROP FUNCTION question_review_projection_guard()")
    op.drop_table("question_selections")
    op.drop_table("question_review_events")
    op.execute("DROP FUNCTION question_selection_guard()")
    op.execute("DROP FUNCTION question_public_content(jsonb)")
    op.execute("DROP FUNCTION question_review_guard()")
    scope = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    parent = "EXISTS (SELECT 1 FROM public.questions q WHERE q.tenant_id=question_versions.tenant_id AND q.id=question_versions.question_id)"
    op.execute(
        f"CREATE POLICY question_version_read ON question_versions FOR SELECT USING (({scope}) AND ({parent}))"
    )
    op.execute(
        f"CREATE POLICY question_version_append ON question_versions FOR INSERT WITH CHECK (({scope}) AND ({parent}) AND authored_by=NULLIF(current_setting('app.actor_user_id', true), '')::uuid)"
    )
    op.drop_constraint("uq_question_versions_review_binding", "question_versions", type_="unique")
    op.execute(
        "CREATE OR REPLACE FUNCTION question_identity_guard() RETURNS trigger LANGUAGE plpgsql\n        SET search_path = pg_catalog, public AS $$\n        BEGIN\n            IF TG_OP = 'DELETE' THEN\n                RAISE EXCEPTION 'Question identity is retained' USING ERRCODE = '42501';\n            END IF;\n            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id\n               OR NEW.created_by IS DISTINCT FROM OLD.created_by OR NEW.created_at IS DISTINCT FROM OLD.created_at\n               OR NEW.revision::bigint <> OLD.revision::bigint + 1 THEN\n                RAISE EXCEPTION 'Only the next revision is allowed' USING ERRCODE = '23514';\n            END IF;\n            RETURN NEW;\n        END $$"
    )
