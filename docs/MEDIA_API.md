# P2-005 private authoring media

Requirements QBK-01, TEN-01, SEC-01, ACC-01, GOV-01. Source/API 0.10.1, schema 0007_authoring_media. Initial supported formats are static PNG and JPEG; PDFs, SVG, animated images, audio, video and candidate-answer uploads are disabled. Wider formats require their own validation/rendering rules. Initial limits: 8 MiB, 20 million pixels, 16 media references per question version. Accessible description: nonblank plain text, 3–1000 characters. Human quality/accessibility review remains necessary; text presence is not accessibility certification.

## Lifecycle and API

Base `/api/v1/tenants/{tenant_id}/media`, normal bearer authentication.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | base | Reserve own pending asset: filename, mime_type, description |
| GET | base/{asset_id} | Own-author/admin lifecycle metadata; other authorized staff receive only safe public descriptors |
| PUT | base/{asset_id}/content?expected_revision=N | Bounded raw binary body with exact reserved Content-Type; validate decoded format/dimensions; capture exact stored object version; enter quarantine |
| POST | base/{asset_id}/scan | Body expected_revision; scan stored exact bytes; clean/rejected or remain quarantined with scan_unavailable |
| GET | base/{asset_id}/content | Authorized clean bytes only; version-specific storage read and length/SHA-256 verification |

Flow: reserve revision 1 → upload revision 2/quarantine → scan revision 3/clean or rejected. Failed scanner attempts retain quarantine, increment revision and permit fenced retry. A missing/tampered object returns 503 without advancing the state; restore the exact version or reserve another asset. Clean/rejected states are terminal. No replace, re-description, deletion or force-clean endpoint exists. A changed description requires a new asset. Upload retries with an old revision conflict rather than silently replacing data.

Reserve example: `{"filename":"triangle.png","mime_type":"image/png","description":"A right triangle with sides labelled 3, 4 and 5 centimetres"}`. Filename extension must match declared MIME; actual format is decoded/verified/reloaded by Pillow; strict structural termination rejects trailing payloads. Bytes are not trusted from filename or MIME alone. Original bytes, including any metadata, are retained privately and scanned; no sanitization or malware-free guarantee is implied. Downloads use a deterministic attachment filename, no-store, nosniff and sandbox headers. No public or presigned object URLs are issued. Later UI uses this protected endpoint with a renderer appropriate to validated types.

Admin/own author can reserve/upload/scan and read their media. Authors cannot discover another author's unattached media. Reviewers obtain media access only through submitted visible versions; coordinators through approved public selections. Retirement removes coordinator access when no other visible approved attachment authorizes it. Candidate/invigilator/examiner have no general media-bank access. Foreign/missing IDs return generic 404. Session/role authority is rechecked after the institution lock. Upload body intake authenticates and checks ownership before reading, releases its read transaction, then reacquires/rechecks authority for mutation. Infrastructure must still enforce request timeouts/concurrency limits; byte limits alone are not denial-of-service capacity proof.

## Frozen question attachments

Question create/full revision accepts optional `media_ids` (unique UUIDs, maximum 16). Omission means empty replacement, matching taxonomy replacement semantics. Only local, clean, authorized and retrievable exact object versions may be attached. Attachments apply to the whole question (or passage group) as an ordered asset-ID list, not arbitrary HTML or per-option inline URLs. Per-child/option positioning is not implemented.

Metadata/history/review, safe staff preview and approved selection responses add `media`: public fields asset_id, mime_type, description, width, height. No object keys, storage version IDs, hashes, scanner engine replies or private marking fields are exposed in that projection. Asset bytes/descriptions are immutable once clean and links are immutable, creation-transaction-only, tenant-composite foreign keys. Later edits cannot alter an older attachment. Body hash remains question-content.v1; version identity binds title/taxonomy/media/review. Metadata-only edits can share the same body hash but must receive fresh approval.

Attachment creation, submit, approve, preview and selection retrieval verify stored exact bytes; missing/broken references fail closed. Storage can become unavailable after a successful check; reads always verify again. No cross-system availability transaction or permanent storage guarantee is claimed. Database state/link guards reject illegal transitions and unclean/late links; the trusted API process performs antivirus verification. SQL triggers do not independently prove an external antivirus verdict against malicious application code or a privileged database owner.

## Storage and scanning

MinIO Python SDK 7.2.20; Pillow 13.0.0; full runtime/dev resolutions pin new dependencies without changing prior package versions. The data adapter uses S3 object version IDs and SHA-256 verified reads, without ETag-as-content-hash assumptions. App storage IAM allows PutObject and GetObjectVersion under authoring/* with a required explicit non-null version query for reads, plus read-only bucket versioning/policy probes; no listing, latest-version GET, deletion or bucket/IAM administration. Bucket versioning must be enabled; the supplied setup creates a private new dedicated bucket with no anonymous bucket policy. Readiness rejects any bucket policy statements. The supplied live tests verify restricted/anonymous access on the actual local server. External S3 provisioning, public-access-block/ACL controls and production support/licensing remain an operator release gate, not an AWS certification claim.

ClamAV uses bounded TCP INSTREAM, exact OK/FOUND interpretation, timeouts and fresh VERSION signature metadata (at most seven days, UTC). Errors/oversized/truncated/unknown replies never become clean. ClamAV TCP has no built-in authentication/encryption: local compose exposes it only on loopback; any remote scanner requires a protected private transport. A clean verdict is a point-in-time result, not proof against future threats. FreshClam signatures update independently from engine image. Engine upgrades, compromise response and re-scan/revocation policy require future operational governance; no rescan mutates existing clean records in this increment.

Safe audit/outbox snapshots contain only asset UUID, revision and state. Raw files, filenames, descriptions, object keys and scanner replies are excluded. Media scanning is an explicit synchronous API operation, not a new outbox worker consumer. Worker remains denied media tables/objects.

Object upload cannot share a PostgreSQL transaction. A failed verification or SQL/audit commit may leave an inaccessible, unreferenced object version; retry uses a fresh opaque key. Never delete potential live object versions to repair a failed upload. No automatic orphan deletion/lifecycle or user quota policy is enabled. SQL mutations/audit/outbox commit together; storage orphan reconciliation/retention/backup and capacity are explicit production gates. Local MinIO volume persists application media; its dedicated test instance is disposable.

## Upstream references and limitations

- https://docs.clamav.net/manual/Usage/ClamdProtocol.html
- https://docs.clamav.net/manual/Installing/Docker.html
- https://pypi.org/project/minio/7.2.20/
- https://pypi.org/project/pillow/13.0.0/
- https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z

Upstream MinIO community repository is archived; the supplied local fixture builds its pinned security release from official source rather than using withdrawn/older images or an unverified mirror. It is a local development fixture, not a supported production storage recommendation. The SDK/adapter does not require the development fixture to be the production backend. Review production hosting, supported storage, AGPL obligations, dependency/container security and data recovery separately before release. Original roadmap/final goal unchanged; P2 remains incomplete until imports and actual accessible browser journeys pass.

0.10.1 correction: existing application storage policy needs refresh-policy because MinIO implicitly matches GetObject through GetObjectVersion. Standard raw EICAR detection is verified separately from format rejection; no appended-signature detection guarantee. See P2_005_FIXES_WINDOWS.md.
