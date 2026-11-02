# Assessment Platform Master Roadmap

Version 1.0 | Baseline date 1 November 2026 | Project owner Muhammad Aslamkhan

This guide is the controlling plan for building an institutional Assessment as a Service platform. It defines the final goal, delivery sequence, requirements, evidence needed to finish each stage, and rules for changing scope. The owner has authorised creation of the guide and the start of development. Detailed defaults below remain explicit assumptions until changed through the decision log.

Final goal
An institution can independently configure its workspace, create and approve questions, assemble and publish an assessment, register candidates, conduct a dependable examination, evaluate responses, resolve reviews, and publish explainable results. The platform can serve multiple institutions safely and expose the same capabilities through integrations.

First customer segment
Schools, colleges, and coaching institutions conducting fixed examinations. Start with a supervised pilot involving one institution, then prove isolation with a second institution. Corporate assessment, recruitment, certification, and adaptive testing remain planned expansion areas.

Definition of the finished product
The final product includes hosted institution and candidate portals, examiner and operator workspaces, versioned assessment APIs, integration support, commercial operations, and evidence for security, recovery, accessibility, and measurement claims. Completing the pilot is an intermediate milestone, not completion of this roadmap.

How to use this guide
Read this baseline before each work session. Select the next incomplete dependency, implement a bounded increment, verify it, and update the progress record. A later phase cannot bypass a failed prerequisite. Dates are planning inputs; evidence determines completion.

# Product Boundaries and Operating Principles

Baseline decisions
DEC 001 Standalone multi tenant assessment product with hosted and API access.
DEC 002 Start with a modular monolith and separate background workers.
DEC 003 FastAPI, PostgreSQL, SQLAlchemy, Alembic, Next.js and TypeScript are the intended application stack. Pin supported versions when integration work starts.
DEC 004 Fixed exams precede adaptive delivery. Educational use is the first vertical.
DEC 005 Published exam content and scoring policies are immutable snapshots.
DEC 006 The server owns timing, permissions, accepted responses, and submission state.
DEC 007 Institution data is private. Operator support access is exceptional and audited.
DEC 008 AI drafts and recommendations require appropriate human review; no unvalidated autonomous consequential grading.

Initial delivery includes
Tenant membership and scoped roles; governed question bank; fixed exam assembly; sections and schedules; candidate import; authenticated participation; accommodations; objective and manual marking; result review and publication; audit; operational recovery.

Deferred from the pilot
Full offline delivery, native mobile applications, marketplace sales, arbitrary custom scripting, remote biometric proctoring, coding execution, CAT, score equating, automatic AI decisions, and jurisdiction specific accreditation claims.

Scope protection
No LMS course management, admissions CRM, hospital functionality, or general HR suite is included. External systems may connect through bounded integrations. English and other subject frameworks are configurable content packages rather than separate engines.

Success priorities
Preserve acknowledged answers, enforce tenant boundaries, make decisions reproducible, and keep candidate workflows accessible. Feature count never substitutes for these outcomes.

# User Journeys and Workspaces

Platform owner
Create and suspend institution accounts, manage entitlements and usage, monitor incidents and jobs, and administer audited support access. Suspension policies must preserve active exam continuity according to a documented rule. Routine operator access does not expose exam answers.

Institution administrator
Configure branding, departments, roles, cohorts, retention, and result policies. Invite staff and candidates. Review usage and manage permitted integrations.

Author and reviewer
Create questions, attach accessible media, assign topics and outcomes, define answer rules or rubrics, preview the candidate rendering, request review, approve or return work, and retire outdated versions.

Assessment coordinator
Choose approved question versions, configure sections and coverage, validate a blueprint, preview the full exam, publish a frozen version, schedule a sitting, register candidates, assign accommodations, and monitor delivery.

Candidate
Accept an invitation, authenticate, complete readiness checks, read instructions, begin within eligibility rules, answer with confirmed save status, recover from interruption, submit, receive a receipt, and view results only after publication.

Examiner and moderator
Receive authorised scripts, mark against the frozen rubric, explain decisions, handle conflicts and moderation, approve corrections, and submit results for institutional publication.

Navigation
Institution workspace: Overview, Question Bank, Assessments, Candidates, Live Exams, Evaluation, Results, Integrations, Settings.
Candidate workspace: Upcoming, Practice, Active Assessments, Results, Certificates.

Design acceptance
Prototype these journeys before broad frontend implementation. Confirm keyboard navigation, mobile and laptop readability, clear error recovery, and visibly different draft, published, and running states. Candidate pages must not reveal keys, hidden rubric answers, or unpublished results.

# Requirement Register

Every implementation task and verification record must reference a requirement ID. Completion requires demonstrable behaviour, not merely the presence of a module.

TEN 01 Tenant boundaries across records, objects, exports, jobs and caches.
IAM 01 Authentication, membership, scoped roles, session controls and privileged action audit.
QBK 01 Versioned questions, media, taxonomy, ownership and approval workflow.
QBK 02 Single choice, multiple select, numeric tolerance, short answer, essay, file upload and passage groups.
ASM 01 Manual and blueprint exam assembly with coverage validation.
PUB 01 Immutable publication snapshots of content, scoring and policies.
SCH 01 Sittings, eligibility, invitations, candidate import and accommodations.
DEL 01 Server deadlines, autosave acknowledgement, reconnect, safe retries and submission receipts.
DEL 02 Navigation policy, review flags, conflict handling and interrupted attempt resolution.
EVA 01 Objective scoring, rubrics, examiner allocation, moderation and appeals.
RES 01 Reviewed publication, corrected result versions, exports and outcome reports.
INT 01 Versioned APIs, scoped credentials, signed webhooks and delivery retry policy.
INT 02 Defined QTI profile and LTI integration according to customer needs.
ACC 01 WCAG 2.2 AA target, keyboard access and tested accommodations.
OPS 01 Monitoring, incident response, load evidence, backup and restore drills.
SEC 01 Threat model, security testing, encryption, secret management and audited support.
COM 01 Institution lifecycle, entitlements, usage metering, billing and support processes.
GOV 01 Decision log, change control, release evidence and progress tracking.
ADV 01 Calibrated item analytics, adaptive delivery and evidence governed score claims.
EXT 01 Multilingual content, certification, recruitment and corporate policy packs.

Allocation
Stages P0 to P6 establish the institutional service. P7 expands interoperability and commercial operations. P8 adds specialised assessment and measurement capabilities. Each deferred requirement stays visible until completed or explicitly removed by an approved roadmap revision.

# Milestones and Dependency Gates

P0 Planning baseline
Deliver this guide, requirement register, decision log, backlog, architecture boundaries and initial progress record. Gate: the scope, final goal and next task are explicit and the baseline is persisted. Status: complete with this delivery; future refinements use change control.

P1 Engineering foundation
Deliver project layout, CI, database and migration setup, tenant membership, authentication, permission enforcement, audit and typed error contracts. Include domain invariants and a repeatable local environment. Gate: fresh setup and migrations succeed; cross tenant API and database tests deny access; CI passes. Current increment covers only a subset of domain rules.

P2 Question bank
Deliver question types, immutable versions, review workflow, media handling, taxonomy, import validation and previews. Gate: approved content can be selected; used content remains unchanged after edits; malformed content and unauthorised media access are rejected.

P3 Exam creation and scheduling
Deliver fixed assembly, blueprint checks, frozen publications, sittings, candidate registration, accommodations and readiness views. Gate: the coordinator can publish and schedule a valid exam; impossible blueprints fail clearly; eligibility and policy snapshots are reproducible.

P4 Reliable candidate delivery
Deliver real candidate runner, persistence backed answer saves, deadline enforcement, conflict controls, reconnect, receipts, interruption handling and live operations. Gate: browser and network interruption tests preserve acknowledged answers; simultaneous retries cannot create conflicting final submissions.

P5 Evaluation and results
Deliver objective and manual grading, rubrics, moderation, appeals, versioned corrections, publication and reports. Gate: an end to end mixed question exam produces explainable results; candidates cannot retrieve unpublished results.

P6 Institutional pilot and production readiness
Deliver supervised pilot, threat review, accessibility review, load validation, recovery drills, support procedures and launch evidence. Gate: the launch checklist on page 9 passes and the owner approves the production release.

P7 Commercial service and integrations
Deliver branding options, entitlements, metering, billing reconciliation, API customer access, webhooks and selected QTI or LTI profiles. Gate: a second institution and an external integration operate without data leakage or accounting ambiguity.

P8 Advanced assessment
Deliver validated specialisations, richer item types, certification and optional adaptive measurement. Gate: each feature has domain appropriate validation and operational evidence. No fixed launch date is promised before staffing and measured throughput are known.

# Architecture and Data Contracts

Runtime architecture
Next.js serves institution, candidate and examiner interfaces. FastAPI hosts bounded modules for identity, tenancy, question bank, assembly, scheduling, delivery, evaluation, results, integration and commercial operations. PostgreSQL stores authoritative records. Workers handle reports, notifications and integrations. Object storage holds protected media and exports. Redis may assist coordination but never becomes the only record of accepted answers.

Core records
Institution, Membership, Role, Permission, Cohort, Candidate, Question, QuestionVersion, MediaAsset, Assessment, AssessmentVersion, Section, Sitting, Registration, Accommodation, Attempt, ResponseRevision, SubmissionReceipt, ScoreRun, MarkingDecision, ResultVersion, Publication, AuditEvent and OutboxEvent.

Boundary rules
Tenant ownership must be explicit. Composite foreign keys and database isolation controls should complement application checks. Tests must exercise direct record IDs, exports, object downloads and worker execution under the wrong tenant. Never trust a tenant ID supplied without verified membership.

Publication contract
Freeze selected item versions, scoring keys, rubrics, order generation policy, navigation and timing policies. Record a content hash and publication identity. Candidate payloads omit secret scoring fields.

Attempt contract
Record registration and publication identity, server start and deadline, accepted response revision and terminal state. Use optimistic concurrency and a defined idempotency contract. Response retries must not overwrite a newer revision. A submission receipt refers to one final response snapshot.

Processing contract
Write business changes and outbox records in the same transaction. Workers consume with idempotent effects and bounded retries. Database commit precedes acknowledgement. Exactly once network delivery is not assumed.

Repository approach
Use backend, frontend, docs and infrastructure directories. Begin with a modular monolith. Extract independent services only when measured load or security isolation requires it. Coding execution and specialist proctoring remain isolated integrations.

# Exam Policies and Measurement Rules

Lifecycle rules
Questions move through draft, review, approved and retired states. Exam versions move through draft, validated, published and archived states. A sitting is separately scheduled, opened, closed or cancelled. An attempt is created, started and finally submitted, expired or invalidated. Evaluation and result publication have separate state machines.

Timing policy
Persist UTC timestamps and show the institution or candidate timezone explicitly. The normal deadline is the earlier of the sitting close and start plus allowed duration. Approved extra time and breaks must follow recorded policy. Starting exactly at close is denied. Deadline extensions require authority, reason and audit. Define accommodation precedence before delivering P3.

Retry and concurrency policy
A repeated answer operation with the same key and identical payload returns its original outcome. A changed payload with the same key is rejected. Stale revisions cannot overwrite accepted responses. Concurrent submissions resolve to one receipt. A reconnect does not extend the timer automatically.

Scoring policy
Specify weights, partial credit, negative marks, numeric tolerance, decimal precision, rounding, unanswered questions and invalid items. Short answer matching must declare its normalisation rules. Manual rubrics and grade boundaries are versioned. Corrections create a new score run and result version with reason and affected candidates.

Score interpretation
Raw marks, percentages, percentiles, competency decisions and model based proficiency estimates remain distinct. Percentiles identify the reference population. Adaptive estimates require calibrated items and validated interpretations. An earlier subject specific simulation does not validate a new population or subject.

Fairness and integrity
Flagged browser events are review evidence, not automatic guilt. Provide human review and an appeal path. AI use must record model and prompt versions, evaluation evidence and reviewer responsibility. High consequence decisions require validation appropriate to their intended use.

# Verification and Quality Strategy

Testing priorities
Use unit tests for domain boundaries, database integration tests for transactional and tenant behaviour, API permission tests, and browser tests for core journeys. Add concurrency, clock boundary, accessibility, load and recovery tests where the risk requires them.

Required failure scenarios
Refresh during an answer save; disconnect before acknowledgement; retry after an uncertain acknowledgement; simultaneous saves from two tabs; server restart during submission; deadline reached during reconnect; worker duplicate delivery; stale scoring job; invalid candidate import; wrong tenant media download; result request before publication; edited question after exam publication.

Definition of done for every feature
Requirements and acceptance criteria are linked. Implementation and migrations are reviewed. Relevant tests pass. Permissions, audit and failure handling are verified. Documentation and progress records are updated. No secrets or real candidate data enter delivered source archives. A UI feature is complete only after its actual journey is exercised.

Release evidence
Record source revision or archive checksum, dependency versions, migration identity, test commands and outcomes, known limitations, deployment and rollback procedure. A test passing in an in memory model is not database or browser evidence.

Initial performance assumptions
Plan a provisional pilot target of 100 simultaneous active candidates with a burst of starts and submissions. This is a target, not measured capacity. Proposed starting objectives are p95 answer save acknowledgement within one second and under 0.1 percent unexpected API failures in the defined test environment. Record workload, hardware, dataset and measurement window. Rebaseline before accepting larger customer commitments.

Recovery objectives
No acknowledged response loss is the application correctness objective. Disaster recovery depends on infrastructure and replication; measure and agree RPO and RTO before production. Run backup restoration into an isolated environment and verify exam and response consistency. Never claim zero disaster data loss without evidence.

# Production Launch and Service Operations

P6 launch checklist
All P1 to P5 gates pass with linked evidence.
One complete institution exam cycle succeeds, including mixed marking, publication and correction.
A second tenant isolation dataset is exercised even if the first pilot has one paying institution.
Load targets are met under the recorded exam workload.
Backup restoration and release rollback are demonstrated.
No unresolved critical or high security finding remains; lower findings have owner and treatment date.
Candidate journeys and accommodations receive accessibility review.
Monitoring identifies save failures, database saturation, job backlog and authentication problems.
An incident response runbook names the operational decision maker and candidate communication process.
Retention, deletion, support access and data handling terms are reviewed for the actual customer jurisdictions before launch.
Owner approval is recorded before deploying the production service.

Commercial readiness
Define the billable unit before metering: a submitted attempt is the baseline proposal. Record cancelled, invalidated, retried and practice attempt treatment. Preserve immutable usage events and reconcile adjustments. Do not interrupt an active exam because a payment webhook arrives late.

Service operations
Separate development, test and production. Keep secrets outside source. Scan uploaded files and restrict file types and sizes. Protect exports with scoped downloads and expiry. Monitor active exam incidents independently of general reporting. Document candidate support, institution escalation, maintenance windows and emergency extension authority.

Capacity and cost
Measure response traffic, database writes, media bandwidth, report generation and support effort per exam. Price after measuring these costs. Avoid unlimited candidate or storage commitments before capacity evidence exists.

Completion of the final programme
P8 closes when all retained requirements pass their gates or have explicit owner approved removal. Further features enter a new version of the roadmap. The operating service then continues through maintenance, incident response and planned releases.

# Change Control and Session Continuity

Authoritative project records
MASTER_ROADMAP.md is the editable baseline; the Word guide is its readable release. BACKLOG.json stores requirement linked work and acceptance criteria. PROGRESS.md records completed evidence, limitations and next task. DECISIONS.md records architecture and product decisions. CHANGELOG.md records delivered increments. AGENTS.md instructs future development sessions to follow these records.

Change process
Record the proposed change, business reason, requirements affected, dependency impact, risks and acceptance criteria. Routine implementation choices within scope may proceed. Changes to final goal, customer segment, contractual promises, data ownership, scoring interpretation, or milestone order require owner agreement. Update the baseline version and log the decision before implementing the changed scope.

Session process
Read the roadmap and current progress. Confirm the actual source state and run relevant baseline checks. Select the next ready backlog task. Keep work bounded and avoid unrelated refactors. Implement and verify. Update evidence, limitations and the next action. Save a coherent handoff containing source and project records.

Blocked work
Record a blocker with evidence. Continue independent tasks within the same milestone if possible. Never mark a milestone complete because a dependency is inconvenient. Do not invent remote access, test results, deployment status or customer approval.

Continuity limitation
A guide cannot guarantee that a future chat automatically retains project state. Resume using the latest project bundle or connected repository and these project records. The repository records, rather than conversational memory alone, determine the next step.

Delivery status
P0 is complete in this package. P1 has started with a dependency free Python domain kernel and tests. It is not an operational SaaS, a database implementation, or a deployed application. The next increment adds the FastAPI and PostgreSQL foundation with tenant membership and enforced permissions.

# Initial Development Backlog

P1 001 Domain invariant foundation
Implement frozen question versions and published exams, tenant ownership checks, candidate safe item projection, eligibility and deadline checks, answer revision conflicts, idempotent retries and one submission receipt. Acceptance: automated tests cover boundaries and rejection paths. Status: implemented and verified in this delivery; in memory only.

P1 002 Application and database foundation
Create pinned FastAPI dependencies, configuration, SQLAlchemy models, Alembic baseline and local PostgreSQL services. Acceptance: a fresh database migrates from zero and health readiness reflects actual dependency state. Status: next.

P1 003 Identity and tenant enforcement
Implement users, tenant membership, scoped roles and authentication. Acceptance: cross tenant reads and writes fail through API and database integration tests; candidate credentials cannot author or grade. Status: queued after P1 002.

P1 004 Transactional audit and delivery contracts
Add audit and outbox persistence, standard errors and API contracts. Acceptance: transactional failures do not create success events; worker replay is safe. Status: queued.

P1 005 Developer and CI environment
Add CI, formatting, static checks, reproducible commands and setup documentation. Acceptance: fresh checkout checks and migrations pass on the supported local environment. Status: queued.

P2 to P5 backlog expansion
Before each milestone begins, split its requirements into tasks with explicit acceptance tests. Preserve phase scope and dependencies from this guide. Include frontend tasks and end to end journeys; backend only delivery does not complete the product.

Planning estimates
Do not promise a completion date from an unmeasured task list. After the first two implementation increments, estimate remaining work using actual throughput, team availability, content readiness and infrastructure constraints. Review estimates at each gate without weakening the acceptance criteria.

# Risks Decisions and Reference Standards

Primary risks and responses
Data leakage between institutions: enforce ownership throughout persistence and storage and prove denial with adversarial tests.
Lost or overwritten answers: transactional storage, acknowledgements, revisions and retry contracts.
Inconsistent scoring: frozen policies, deterministic runs, moderation and correction history.
Excessive initial scope: fixed pilot boundary and dependency gated stages.
Unfounded measurement claims: evidence status and domain specific validation.
Weak operational readiness: measured load, restore drills and explicit release approval.
Poor content quality: review workflow, item analytics and author responsibility.

Decisions still to resolve before their implementation gates
Product name and domain before branding work.
Pilot institution, subjects, candidate age groups and exam policies before P3.
Supported browsers, hosting region, customer jurisdictions and retention before P6.
Final concurrency target, RPO, RTO and service commitments before production contracting.
Pricing, invoicing provider and tax treatment before P7 commercial launch.
QTI import and export profile and target LMS before integration implementation.
Adaptive use case, item calibration data and evidence criteria before P8.

Reference standards
QTI supports interchange of questions and tests. Plan an explicit supported profile and test actual interoperability; do not claim certification without completing its process.
https://www.1edtech.org/standards/qti
LTI supports learning platform integration. Choose services against customer needs and verify with the target platform.
https://www.1edtech.org/standards/lti
WCAG 2.2 provides the accessibility reference. AA is the target; conformance requires testing the delivered product.
https://www.w3.org/TR/WCAG22/

Standards references guide future implementation, not a claim that this initial package implements them. Recheck specifications and supported dependency versions when the corresponding work starts.