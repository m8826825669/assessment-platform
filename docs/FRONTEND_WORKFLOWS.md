# P2-007 institution workspace and journey specification

Requirements: QBK-01, QBK-02, IAM-01, ACC-01; preserves TEN-01, SEC-01, GOV-01. This is the first institution interface, not a candidate examination runner or a production release. Visual direction: quiet forest green, warm white surfaces, serif headings, compact catalogue table, explicit workflow states and amber staff-only marking regions. No marketing imagery is needed for this task-oriented workspace.

## Journey and screen contract

| Actor | Screen / action | Server boundary / recovery |
| --- | --- | --- |
| Staff | Sign in, choose an active institution, sign out | Existing opaque bearer session; institution list and access permissions from API. No public registration or remembered token. Refresh requires login. |
| Author / admin | Bank, title/type/state/classification filters, 20-row paging | Existing permission-filtered collection. Own-author/admin scope stays on server. Empty results are not fabricated examples. |
| Author / admin | New question, structured editor for seven types, taxonomy and clean image attachments | Positive decimal strings, option IDs, rubric totals, group children and response policies validated by existing backend. New versions require exact root revision. Amber sections contain staff marking material. |
| Author / admin | Save draft, immutable history, inspect old version, saved candidate rendering | Each save appends. Validation/conflict preserves current form. Reload/discard is explicit; unsaved tab close warns. History inspection is read-only. Old preview does not mutate working content. |
| Author / admin | Submit draft, inspect private feedback | Exact root revision, version hash and review counter. New edits create a draft; prior approval never transfers. |
| Independent reviewer / admin | Queue, private marking detail, candidate rendering, approve or return | Server denies origin/editor/submitter self-approval. Return reason required. Reviewer preview endpoint returns only existing v1 candidate projection and verified media; no staff hash/keys. |
| Admin / reviewer | Retire approved exact version from loaded detail | Reason and current revision/review counters required. History inspect enables old-version retirement for an authorized admin; historical references remain. |
| Coordinator / admin | Approved versions and candidate-safe preview | Selection endpoint returns approved non-retired public snapshots only. No editor/private marking request is made for coordinators. P3 assessment assembly is deferred. |
| Author / admin | Reserve image, upload, scan/retry, attach clean asset; recover by asset ID | PNG/JPEG 8 MiB; required immutable accessible description; separate state/revision controls; no listing or public URLs. Scan errors retain quarantine and asset ID; rejected bytes cannot attach. Protected blob URLs are revoked on unmount. |
| Author / admin | JSON preview, review rows, key, commit/retry, recover owned receipt | Original bytes go to server parser (duplicate keys preserved for rejection). A commit attempt freezes bytes/key, including uncertain network failure. Explicit new-batch action warns about uncertain prior success. Receipts acknowledge original creation rather than current state. |
| Admin | Create, rename or retire subject/topic/outcome/tag | Existing catalogue/revision API; topic requires active subject. Snapshots keep old labels. Initial picker loads at most 10,000 active terms; very large catalogues need a future searchable picker. |

## Local startup

Node 22 or newer; `npm ci`, `npm run typecheck`, `npm run format:check`, `npm test`, `npm run build`. Start existing API on 127.0.0.1:8000, then from frontend `npm run dev` (127.0.0.1:3000). Visit http://127.0.0.1:3000. Default upstream is local API; optional frontend/.env.local can set ASSESSMENT_API_ORIGIN=http://127.0.0.1:8000. Never put database/storage credentials into frontend environment.

The Node proxy is server-side with fixed configured origin, bounded request buffers (2 MiB normal/import and 8 MiB media), an explicit authorization/content-type/idempotency-key header allowlist, no cookie forwarding, no redirects and no-store response headers. No CORS changes, server-side account store or second identity system are added. Body buffers and synchronous scan requests are initial engineering limits, not production capacity claims. CSP allows Next development tooling; a production nonce/CSP hardening and deployment review remains P6.

## Verification boundary

Component/SSR tests deliberately inject private fields into all seven candidate renderer branches and check that only public fields render and text is escaped. Proxy checks do not substitute for live API traffic. Backend adds seven real-database reviewer-preview cases. Standard Python suite collects 659 tests; the separate browser harness is deliberately outside default testpaths.

`python scripts/verify_browser.py` (using backend venv, from any directory) reads only migration credentials privately for disposable fixtures, then starts a loopback restricted API on an ephemeral port and a temporary Next server on 14173. It creates synthetic author/reviewer/coordinator accounts only in a random test database and uses the dedicated storage fixture on 19010 plus ClamAV 13310. It runs three Playwright scenarios, fails on missing prerequisites and cleans its owned API/database/storage afterward. Playwright owns/stops its own Next child. Keep 14173 free; no existing application server is reused. `npm run test:browser` alone is intentionally rejected without fixture configuration.

Actual browser checks include seven-type import and immutable save/submit/independent approval/coordinator rendering; safe preview response traffic; approved snapshot stability after new draft; real scanned accessible image; narrow viewport; stale two-tab save with retained form/reload; keyboard focus after error; role-restricted controls and second-tenant listing; invalid import recovery. This is not a complete WCAG audit. Manual keyboard/screen-reader/review-return/retirement checks still need owner evidence. No browser pass was executed in the authoring environment: managed preview launcher supplied unsupported Next CLI arguments. No database/storage/browser claims are inferred from a successful build.

CI retains the existing three PostgreSQL/Python and Windows jobs, and adds frontend checks/build and the real browser gate to Python 3.12. Actual new-commit CI and owner browser evidence are required before P2-008. No deployment occurs.

## Known limits

No auto-save or persisted draft cache; no candidate response submission/grade; internal JSON imports only; authoring media remains PNG/JPEG. Refresh loses in-memory unsaved work/import key, so retain uncertain import keys privately before reloading. UI role visibility is convenience, never authorization. Current review-decision display uses the API's first 100 entries; raw JSON staff inspection is functional but can be improved later. No branding management, membership administration UI, platform operator console, assessments or candidate navigation is added in P2. Keep all deferred roadmap items visible.
