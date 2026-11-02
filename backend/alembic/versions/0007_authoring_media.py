"""Private authoring media and frozen version attachments. SEC-01, ACC-01, TEN-01."""

from alembic import op

revision = "0007_authoring_media"
down_revision = "0006_question_taxonomy"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE TABLE media_assets (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_by UUID NOT NULL, \n\tfilename VARCHAR(160) NOT NULL, \n\tmime_type VARCHAR(40) NOT NULL, \n\tdescription VARCHAR(1000) NOT NULL, \n\tstate VARCHAR(20) DEFAULT 'pending' NOT NULL, \n\trevision INTEGER DEFAULT '1' NOT NULL, \n\tobject_key VARCHAR(160), \n\tobject_version VARCHAR(256), \n\tdigest VARCHAR(64), \n\tbyte_length INTEGER, \n\twidth INTEGER, \n\theight INTEGER, \n\tscanner_version VARCHAR(200), \n\terror_code VARCHAR(40), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_media_assets PRIMARY KEY (id), \n\tCONSTRAINT uq_media_assets_tenant_id UNIQUE (tenant_id, id), \n\tCONSTRAINT ck_media_assets_mime_type CHECK (mime_type IN ('image/png','image/jpeg')), \n\tCONSTRAINT ck_media_assets_description CHECK (length(trim(description)) BETWEEN 3 AND 1000), \n\tCONSTRAINT ck_media_assets_state_revision CHECK (state IN ('pending','quarantine','clean','rejected') AND revision > 0), \n\tCONSTRAINT ck_media_assets_stored_bytes CHECK ((state='pending' AND object_key IS NULL AND object_version IS NULL AND digest IS NULL AND byte_length IS NULL AND width IS NULL AND height IS NULL) OR (state<>'pending' AND object_key IS NOT NULL AND object_version IS NOT NULL AND object_version <> 'null' AND digest IS NOT NULL AND byte_length IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL AND digest ~ '^[0-9a-f]{64}$' AND byte_length BETWEEN 1 AND 8388608 AND width > 0 AND height > 0 AND width::bigint*height <= 20000000)), \n\tCONSTRAINT fk_media_assets_tenant_id_institutions FOREIGN KEY(tenant_id) REFERENCES institutions (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_media_assets_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT\n)"
    )
    op.execute("CREATE INDEX ix_media_assets_tenant_creator ON media_assets (tenant_id, created_by, id)")
    op.execute(
        "CREATE TABLE question_version_media (\n\ttenant_id UUID NOT NULL, \n\tversion_id UUID NOT NULL, \n\tasset_id UUID NOT NULL, \n\tquestion_id UUID NOT NULL, \n\tCONSTRAINT pk_question_version_media PRIMARY KEY (tenant_id, version_id, asset_id), \n\tCONSTRAINT fk_version_media_version FOREIGN KEY(tenant_id, question_id, version_id) REFERENCES question_versions (tenant_id, question_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_version_media_asset FOREIGN KEY(tenant_id, asset_id) REFERENCES media_assets (tenant_id, id) ON DELETE RESTRICT\n)"
    )
    op.execute(
        "CREATE INDEX ix_version_media_asset_version ON question_version_media (tenant_id, asset_id, version_id)"
    )
    actor = "NULLIF(current_setting('app.actor_user_id',true),'')::uuid"
    scope = "tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid"
    own = f"""EXISTS (SELECT 1 FROM public.memberships m JOIN public.users u ON u.id=m.user_id
        JOIN public.institutions i ON i.id=m.tenant_id WHERE m.tenant_id=media_assets.tenant_id AND m.user_id={actor}
        AND m.status='active' AND i.status='active' AND u.is_active AND
        (m.role='admin' OR (m.role='author' AND media_assets.created_by={actor})))"""
    private = "EXISTS (SELECT 1 FROM public.question_versions v WHERE v.tenant_id=question_version_media.tenant_id AND v.question_id=question_version_media.question_id AND v.id=question_version_media.version_id)"
    public = "EXISTS (SELECT 1 FROM public.question_selections s WHERE s.tenant_id=question_version_media.tenant_id AND s.version_id=question_version_media.version_id AND s.state='approved')"
    for table in ["media_assets", "question_version_media"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY media_link_read ON question_version_media FOR SELECT USING (({scope}) AND (({private}) OR ({public})))"
    )
    op.execute(
        f"CREATE POLICY media_link_append ON question_version_media FOR INSERT WITH CHECK (({scope}) AND ({private}))"
    )
    attached = "EXISTS (SELECT 1 FROM public.question_version_media l WHERE l.tenant_id=media_assets.tenant_id AND l.asset_id=media_assets.id)"
    op.execute(
        f"CREATE POLICY media_read ON media_assets FOR SELECT USING (({scope}) AND (({own}) OR ({attached})))"
    )
    op.execute(
        f"CREATE POLICY media_reserve ON media_assets FOR INSERT WITH CHECK (({scope}) AND ({own}) AND created_by={actor})"
    )
    op.execute(
        f"CREATE POLICY media_change ON media_assets FOR UPDATE USING (({scope}) AND ({own})) WITH CHECK (({scope}) AND ({own}))"
    )
    op.execute("""CREATE FUNCTION media_asset_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog,public AS $$
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Media history is retained' USING ERRCODE='42501'; END IF;
            PERFORM id FROM public.institutions WHERE id=NEW.tenant_id FOR UPDATE;
            IF TG_OP='INSERT' THEN
                IF NEW.state<>'pending' OR NEW.revision<>1 OR NEW.scanner_version IS NOT NULL OR NEW.error_code IS NOT NULL THEN
                    RAISE EXCEPTION 'New media starts pending' USING ERRCODE='23514'; END IF;
                RETURN NEW;
            END IF;
            IF NEW.revision::bigint<>OLD.revision::bigint+1 OR OLD.state NOT IN ('pending','quarantine') THEN
                RAISE EXCEPTION 'Media revision or terminal state conflict' USING ERRCODE='23514'; END IF;
            IF OLD.state='pending' THEN
                IF NEW.state<>'quarantine' OR NEW.scanner_version IS NOT NULL OR NEW.error_code IS NOT NULL OR
                    (to_jsonb(NEW)-ARRAY['state','revision','object_key','object_version','digest','byte_length','width','height'])
                    IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','revision','object_key','object_version','digest','byte_length','width','height']) THEN
                    RAISE EXCEPTION 'Only initial byte capture may leave pending' USING ERRCODE='23514'; END IF;
            ELSE
                IF (to_jsonb(NEW)-ARRAY['state','revision','scanner_version','error_code'])
                    IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','revision','scanner_version','error_code']) OR
                    NOT ((NEW.state IN ('clean','rejected') AND NEW.scanner_version IS NOT NULL AND NEW.error_code IS NULL)
                        OR (NEW.state='quarantine' AND NEW.scanner_version IS NULL AND NEW.error_code='scan_unavailable')) THEN
                    RAISE EXCEPTION 'Stored bytes and descriptions are immutable' USING ERRCODE='23514'; END IF;
            END IF;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER media_asset_guard BEFORE INSERT OR UPDATE OR DELETE ON media_assets FOR EACH ROW EXECUTE FUNCTION media_asset_guard()"
    )
    op.execute("""CREATE FUNCTION version_media_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog,public AS $$
        DECLARE creation bigint; number integer; revision integer; asset public.media_assets%ROWTYPE;
        BEGIN
            IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Version media is immutable' USING ERRCODE='42501'; END IF;
            SELECT v.created_txid,v.version_number,q.revision INTO creation,number,revision FROM public.question_versions v
                JOIN public.questions q ON q.tenant_id=v.tenant_id AND q.id=v.question_id
                WHERE v.tenant_id=NEW.tenant_id AND v.question_id=NEW.question_id AND v.id=NEW.version_id;
            IF creation IS NULL OR creation<>txid_current() OR number<>revision OR EXISTS
                (SELECT 1 FROM public.question_review_events e WHERE e.tenant_id=NEW.tenant_id AND e.version_id=NEW.version_id) THEN
                RAISE EXCEPTION 'Attachments belong to version creation only' USING ERRCODE='23514'; END IF;
            SELECT * INTO asset FROM public.media_assets WHERE tenant_id=NEW.tenant_id AND id=NEW.asset_id AND state='clean';
            IF asset.id IS NULL OR NOT EXISTS (SELECT 1 FROM public.memberships m WHERE m.tenant_id=NEW.tenant_id
                AND m.user_id=NULLIF(current_setting('app.actor_user_id',true),'')::uuid AND m.status='active'
                AND (m.role='admin' OR (m.role='author' AND asset.created_by=m.user_id))) THEN
                RAISE EXCEPTION 'Clean owned media required' USING ERRCODE='23514'; END IF;
            IF (SELECT count(*) FROM public.question_version_media l WHERE l.tenant_id=NEW.tenant_id AND l.version_id=NEW.version_id)>=16 THEN
                RAISE EXCEPTION 'Too many media attachments' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER version_media_guard BEFORE INSERT OR UPDATE OR DELETE ON question_version_media FOR EACH ROW EXECUTE FUNCTION version_media_guard()"
    )


def downgrade():
    op.execute("DROP POLICY media_read ON media_assets")
    op.drop_table("question_version_media")
    op.drop_table("media_assets")
    op.execute("DROP FUNCTION version_media_guard()")
    op.execute("DROP FUNCTION media_asset_guard()")
