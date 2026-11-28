"use client";
import { FormEvent, useEffect, useRef, useState } from "react";
import { ApiError, request } from "../lib/api";
import { Row, Term } from "../lib/types";
import {
  Blueprint,
  Draft,
  Operation,
  Publication,
  Section,
  Sitting,
  Validation,
  diagnosticText,
  emptyBlueprint,
  requireId,
  scheduleInstant,
} from "../lib/exams";
import { invitationTime } from "../lib/invitations";
import CandidatePreview from "./candidate-preview";

export function PublicationSummary({
  publication,
  base,
  token,
}: {
  publication: Publication;
  base: string;
  token: string;
}) {
  return (
    <section className="panel" aria-label="Frozen publication">
      <h2>Frozen publication</h2>
      <p className="reference">Publication ID: {publication.id}</p>
      <p>
        Base duration: {publication.policy.duration_minutes} minutes · item
        weight {publication.policy.item_weight} · negative marks{" "}
        {publication.policy.negative_marks} · unanswered points{" "}
        {publication.policy.unanswered_points}.
      </p>
      <p>
        Percentage: {publication.policy.percentage_decimal_places} decimal
        places, {publication.policy.percentage_rounding.replaceAll("_", " ")}.
        Invalid items: {publication.policy.invalid_items}. This pilot policy is
        read-only.
      </p>
      {publication.sections.map((section, index) => (
        <section key={index}>
          <h3>
            Published section {index + 1} · {section.items.length} selection(s)
          </h3>
          {section.items.map((item) => (
            <details key={item.version_id}>
              <summary>{item.title}</summary>
              <p className="reference">Exact version: {item.version_id}</p>
              <CandidatePreview
                preview={{ content: item.content, media: item.media }}
                base={base}
                token={token}
              />
            </details>
          ))}
        </section>
      ))}
    </section>
  );
}
export default function ExamWorkspace({
  tenant,
  token,
  terms,
  onDirtyChange,
  onSessionExpired,
}: {
  tenant: string;
  token: string;
  terms: Term[];
  onDirtyChange: (dirty: boolean) => void;
  onSessionExpired: () => void;
}) {
  const [blueprint, setBlueprint] = useState<Blueprint>(emptyBlueprint);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [publication, setPublication] = useState<Publication | null>(null);
  const [sitting, setSitting] = useState<Sitting | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [offset, setOffset] = useState(0);
  const [target, setTarget] = useState(0);
  const [reference, setReference] = useState("");
  const [history, setHistory] = useState<Draft[]>([]);
  const [preview, setPreview] = useState<Row | null>(null);
  const [pending, setPending] = useState<Operation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [notice, setNotice] = useState("");
  const [title, setTitle] = useState("");
  const [opening, setOpening] = useState("");
  const [closing, setClosing] = useState("");
  const [zone, setZone] = useState("UTC");
  const [sittingReference, setSittingReference] = useState("");
  const active = useRef(true),
    mutex = useRef(false);
  const alertRef = useRef<HTMLDivElement>(null);
  const expire = useRef(onSessionExpired);
  expire.current = onSessionExpired;
  const base = `tenants/${tenant}`;
  const changed =
    JSON.stringify(blueprint) !==
    JSON.stringify(draft ? { sections: draft.sections } : emptyBlueprint());
  const dirty = changed || !!pending || !!title || !!opening || !!closing;
  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      onDirtyChange(false);
    };
  }, [onDirtyChange]);
  useEffect(() => {
    if (error) alertRef.current?.focus();
  }, [error]);
  async function run(work: () => Promise<void>) {
    if (mutex.current) return;
    mutex.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      await work();
    } catch (problem) {
      if (!active.current) return;
      if (problem instanceof ApiError && problem.status === 401) {
        expire.current();
        return;
      }
      if (problem instanceof ApiError && [403, 404].includes(problem.status)) {
        setPublication(null);
        setPreview(null);
        setSitting(null);
      }
      if (problem instanceof ApiError && problem.status === 403) {
        setRows([]);
        setDraft(null);
        setBlueprint(emptyBlueprint());
        setHistory([]);
        setValidation(null);
        setPending(null);
      }
      setError(
        problem instanceof Error
          ? problem
          : new Error(
              "Request failed. Retain the recovery reference and retry.",
            ),
      );
    } finally {
      mutex.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function catalogue(next: number) {
    setRows(null);
    const result = await request<Row[]>(
      `${base}/question-selections?offset=${next}&limit=20`,
      token,
    );
    if (active.current) {
      setRows(result);
      setOffset(next);
    }
  }
  useEffect(() => {
    void run(() => catalogue(0));
  }, []); // tenant/session-keyed instance
  function edit(sections: Section[]) {
    setBlueprint({ sections });
    setValidation(null);
    setPublication(null);
    setSitting(null);
  }
  function section(index: number, patch: Partial<Section>) {
    edit(
      blueprint.sections.map((row, position) =>
        position === index ? { ...row, ...patch } : row,
      ),
    );
  }
  function leave() {
    return (
      !dirty ||
      window.confirm(
        "Discard unsaved changes? Copy recovery IDs for any unconfirmed requests first.",
      )
    );
  }
  async function loadDraft(id: string, latest = false) {
    requireId(id);
    const result = await request<Draft>(
      `${base}/exam-blueprints/drafts/${id}`,
      token,
    );
    const revisions = await request<Draft[]>(
      `${base}/exam-blueprints/drafts/${id}/history`,
      token,
    );
    if (!active.current) return;
    const chosen = latest ? revisions.at(-1)! : result;
    setDraft(chosen);
    setBlueprint({ sections: chosen.sections });
    setReference(chosen.id);
    setHistory(revisions);
    setValidation(null);
    setPublication(null);
    setSitting(null);
    setPending(null);
    setTitle("");
    setOpening("");
    setClosing("");
    setNotice(
      `Loaded draft revision ${chosen.revision}. Validate before publishing.`,
    );
  }
  async function execute(operation: Operation) {
    setPending(operation);
    let result: Draft | Publication | Sitting;
    try {
      result = await request<Draft | Publication | Sitting>(
        operation.path,
        token,
        {
          method: operation.method,
          ...(operation.body ? { body: operation.body } : {}),
        },
      );
    } catch (problem) {
      if (active.current && problem instanceof ApiError && problem.status < 500)
        setPending(null);
      throw problem;
    }
    if (!active.current) return;
    setPending(null);
    if (operation.kind === "draft") {
      const saved = result as Draft;
      setDraft(saved);
      setBlueprint({ sections: saved.sections });
      setReference(saved.id);
      setHistory([]);
      setPublication(null);
      setValidation(null);
      setNotice(
        `Draft revision ${saved.revision} saved. Retain its draft ID; validate before publishing.`,
      );
    } else if (operation.kind === "publication") {
      setPublication(result as Publication);
      setNotice("Publication saved. Its content and policy are frozen.");
    } else {
      setSitting(result as Sitting);
      setSittingReference(result.id);
      setTitle("");
      setOpening("");
      setClosing("");
      setNotice("Sitting saved. Candidate registration is a separate step.");
    }
  }
  function save() {
    const identity = crypto.randomUUID();
    void run(() =>
      execute(
        draft
          ? {
              kind: "draft",
              identity,
              path: `${base}/exam-blueprints/drafts/${draft.id}/revisions`,
              method: "POST",
              body: JSON.stringify({
                ...blueprint,
                id: identity,
                expected_revision: draft.revision,
              }),
            }
          : {
              kind: "draft",
              identity,
              path: `${base}/exam-blueprints/drafts/${identity}`,
              method: "PUT",
              body: JSON.stringify(blueprint),
            },
      ),
    );
  }
  async function validate() {
    const result = await request<Validation>(
      `${base}/exam-blueprints/validate`,
      token,
      { method: "POST", body: JSON.stringify(blueprint) },
    );
    if (active.current) setValidation(result);
  }
  async function recoverPublication() {
    const result = await request<Publication>(
      `${base}/exam-blueprints/publications/${requireId(reference.trim())}`,
      token,
    );
    if (active.current) {
      setPublication(result);
      setDraft(null);
      setBlueprint(emptyBlueprint());
      setHistory([]);
      setValidation(null);
      setTitle("");
      setOpening("");
      setClosing("");
      setSitting(null);
    }
  }
  function schedule(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      if (!publication) return;
      const identity = crypto.randomUUID();
      const payload = {
        publication_id: publication.id,
        title,
        opens_at: scheduleInstant(opening, zone),
        closes_at: scheduleInstant(closing, zone),
        display_timezone: zone,
      };
      await execute({
        kind: "sitting",
        identity,
        path: `${base}/exam-sittings/${identity}`,
        method: "PUT",
        body: JSON.stringify(payload),
      });
    });
  }
  const locked = busy || !!pending;
  return (
    <section aria-label="Exam assembly" aria-busy={busy}>
      <div className="page-heading">
        <div>
          <div className="eyebrow">Coordinator workspace</div>
          <h1>Assemble an exam</h1>
          <p>
            Choose exact approved versions, validate the blueprint, then publish
            and schedule.
          </p>
        </div>
        <button
          className="secondary"
          disabled={locked}
          onClick={() => {
            if (leave()) {
              setBlueprint(emptyBlueprint());
              setDraft(null);
              setReference("");
              setPublication(null);
              setSitting(null);
              setValidation(null);
              setHistory([]);
              setTitle("");
              setOpening("");
              setClosing("");
            }
          }}
        >
          New exam
        </button>
      </div>
      <p className="notice">
        Fixed pilot: published base duration is 30 minutes. Publication and
        sitting snapshots cannot be edited. Candidate registration and delivery
        are separate steps.
      </p>
      {error && (
        <div
          className="notice error"
          role="alert"
          aria-label="Exam request error"
          tabIndex={-1}
          ref={alertRef}
        >
          <strong>{error.message}</strong>
          {error instanceof ApiError && error.requestId && (
            <p>Support reference: {error.requestId}</p>
          )}
        </div>
      )}
      {notice && (
        <p role="status" className="notice success">
          {notice}
        </p>
      )}
      {busy && <p role="status">Checking with your institution…</p>}
      {pending && (
        <div className="notice" role="status">
          <p>
            Request outcome is unconfirmed. Retain this {pending.kind} recovery
            ID: <span className="reference">{pending.identity}</span>. Retry
            uses the exact original request.
          </p>
          <button
            disabled={busy}
            onClick={() => void run(() => execute(pending))}
          >
            Retry same request
          </button>
        </div>
      )}
      <section className="panel">
        <h2>Reopen by reference</h2>
        <p>
          Drafts do not have a catalogue yet. Retain the displayed ID to reopen
          an exact revision or publication after signing in again.
        </p>
        <label>
          Draft or publication ID
          <input
            value={reference}
            disabled={locked}
            onChange={(e) => setReference(e.target.value)}
          />
        </label>
        <div className="inline">
          <button
            className="secondary"
            disabled={locked || !reference}
            onClick={() => {
              if (leave()) void run(() => loadDraft(reference.trim()));
            }}
          >
            Open draft
          </button>
          <button
            className="secondary"
            disabled={locked || !reference}
            onClick={() => {
              if (leave()) void run(recoverPublication);
            }}
          >
            Open publication
          </button>
          {draft && (
            <button
              className="secondary"
              disabled={locked}
              onClick={() => {
                if (leave()) void run(() => loadDraft(draft.id, true));
              }}
            >
              Reload latest revision
            </button>
          )}
        </div>
        {draft && (
          <div className="notice">
            <strong>Draft revision {draft.revision}</strong>
            <p className="reference">Draft ID: {draft.id}</p>
            <p className="reference">Exam lineage: {draft.exam_id}</p>
          </div>
        )}
        {history.length > 0 && (
          <details>
            <summary>Saved revision history</summary>
            <ol>
              {history.map((row) => (
                <li className="reference" key={row.id}>
                  Revision {row.revision}: {row.id}
                </li>
              ))}
            </ol>
          </details>
        )}
      </section>
      <div className="exam-columns">
        <section className="panel">
          <h2>Approved question versions</h2>
          <p>
            Add exact versions to the target section. An entire passage group
            counts as one selection.
          </p>
          <label>
            Target section
            <select
              disabled={locked || !blueprint.sections.length}
              value={target}
              onChange={(e) => setTarget(Number(e.target.value))}
            >
              {blueprint.sections.map((_, i) => (
                <option key={i} value={i}>
                  Section {i + 1}
                </option>
              ))}
            </select>
          </label>
          {!rows ? (
            <p role="status">Loading approved versions…</p>
          ) : rows.length === 0 ? (
            <p>No approved versions on this page.</p>
          ) : (
            <ul className="exam-selections">
              {rows.map((row) => (
                <li key={row.version_id}>
                  <strong>{row.title}</strong>
                  <p className="reference">{row.version_id}</p>
                  <div className="inline">
                    <button
                      className="secondary"
                      disabled={
                        locked ||
                        !blueprint.sections.length ||
                        blueprint.sections[target]?.version_ids.length >= 100
                      }
                      onClick={() =>
                        section(target, {
                          version_ids: [
                            ...blueprint.sections[target].version_ids,
                            row.version_id,
                          ],
                        })
                      }
                      aria-label={`Add version: ${row.title}`}
                    >
                      Add to section
                    </button>
                    <button
                      className="quiet"
                      disabled={locked}
                      onClick={() =>
                        void run(async () => {
                          const result = await request<Row>(
                            `${base}/question-selections/${row.version_id}`,
                            token,
                          );
                          if (active.current) setPreview(result);
                        })
                      }
                      aria-label={`Preview version: ${row.title}`}
                    >
                      Preview
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="inline">
            <button
              className="secondary"
              disabled={locked || offset === 0}
              onClick={() =>
                void run(() => catalogue(Math.max(0, offset - 20)))
              }
            >
              Previous approved
            </button>
            <span>Page {Math.floor(offset / 20) + 1}</span>
            <button
              className="secondary"
              disabled={locked || !rows || rows.length < 20}
              onClick={() => void run(() => catalogue(offset + 20))}
            >
              Next approved
            </button>
            <button
              className="quiet"
              disabled={locked}
              onClick={() => void run(() => catalogue(offset))}
            >
              Refresh approved
            </button>
          </div>
        </section>
        <section className="panel">
          <h2>Ordered sections</h2>
          <fieldset disabled={locked} className="content-fields">
            {blueprint.sections.map((row, index) => (
              <fieldset key={index}>
                <legend>Section {index + 1}</legend>
                <div className="two-fields">
                  <label>
                    Section {index + 1} minimum
                    <input
                      type="number"
                      min={0}
                      max={500}
                      value={row.minimum}
                      onChange={(e) =>
                        section(index, { minimum: Number(e.target.value) })
                      }
                    />
                  </label>
                  <label>
                    Section {index + 1} maximum
                    <input
                      type="number"
                      min={0}
                      max={500}
                      value={row.maximum}
                      onChange={(e) =>
                        section(index, { maximum: Number(e.target.value) })
                      }
                    />
                  </label>
                </div>
                <ol className="exam-selected">
                  {row.version_ids.map((id, position) => (
                    <li key={`${id}:${position}`}>
                      <p>
                        {rows?.find((item) => item.version_id === id)?.title ??
                          "Saved exact version"}
                      </p>
                      <p className="reference">{id}</p>
                      <div className="inline">
                        <button
                          className="quiet"
                          aria-label={`Remove selection ${position + 1} from section ${index + 1}`}
                          onClick={() =>
                            section(index, {
                              version_ids: row.version_ids.filter(
                                (_, i) => i !== position,
                              ),
                            })
                          }
                        >
                          Remove
                        </button>
                        {[-1, 1].map((direction) => (
                          <button
                            key={direction}
                            className="quiet"
                            disabled={
                              position + direction < 0 ||
                              position + direction >= row.version_ids.length
                            }
                            aria-label={`Move selection ${position + 1} ${direction < 0 ? "up" : "down"} in section ${index + 1}`}
                            onClick={() => {
                              const next = [...row.version_ids];
                              [next[position], next[position + direction]] = [
                                next[position + direction],
                                next[position],
                              ];
                              section(index, { version_ids: next });
                            }}
                          >
                            {direction < 0 ? "↑" : "↓"}
                          </button>
                        ))}
                      </div>
                    </li>
                  ))}
                </ol>
                {row.coverage.map((rule, ruleIndex) => (
                  <fieldset key={ruleIndex}>
                    <legend>Coverage rule {ruleIndex + 1}</legend>
                    <label>
                      Section {index + 1} rule {ruleIndex + 1} taxonomy ID
                      <input
                        list="exam-taxonomy"
                        value={rule.term_id}
                        onChange={(e) =>
                          section(index, {
                            coverage: row.coverage.map((value, i) =>
                              i === ruleIndex
                                ? { ...value, term_id: e.target.value }
                                : value,
                            ),
                          })
                        }
                      />
                    </label>
                    <div className="two-fields">
                      {(["minimum", "maximum"] as const).map((key) => (
                        <label key={key}>
                          Section {index + 1} rule {ruleIndex + 1} {key}
                          <input
                            type="number"
                            min={0}
                            max={500}
                            value={rule[key]}
                            onChange={(e) =>
                              section(index, {
                                coverage: row.coverage.map((value, i) =>
                                  i === ruleIndex
                                    ? {
                                        ...value,
                                        [key]: Number(e.target.value),
                                      }
                                    : value,
                                ),
                              })
                            }
                          />
                        </label>
                      ))}
                    </div>
                    <button
                      className="quiet"
                      onClick={() =>
                        section(index, {
                          coverage: row.coverage.filter(
                            (_, i) => i !== ruleIndex,
                          ),
                        })
                      }
                    >
                      Remove coverage rule {ruleIndex + 1}
                    </button>
                  </fieldset>
                ))}
                <div className="inline">
                  <button
                    className="secondary"
                    disabled={row.coverage.length >= 25}
                    onClick={() =>
                      section(index, {
                        coverage: [
                          ...row.coverage,
                          { term_id: "", minimum: 1, maximum: 1 },
                        ],
                      })
                    }
                  >
                    Add coverage rule to section {index + 1}
                  </button>
                  <button
                    className="quiet"
                    onClick={() => {
                      edit(blueprint.sections.filter((_, i) => i !== index));
                      setTarget(0);
                    }}
                  >
                    Remove section {index + 1}
                  </button>
                </div>
              </fieldset>
            ))}
            <datalist id="exam-taxonomy">
              {terms.map((term) => (
                <option value={term.id} key={term.id}>
                  {term.label}
                </option>
              ))}
            </datalist>
            <button
              className="secondary"
              disabled={blueprint.sections.length >= 20}
              onClick={() =>
                edit([...blueprint.sections, emptyBlueprint().sections[0]])
              }
            >
              Add section
            </button>
          </fieldset>
          <div className="inline">
            <button disabled={locked} onClick={() => void run(validate)}>
              Validate blueprint
            </button>
            <button
              className="secondary"
              disabled={locked || (!!draft && !changed)}
              onClick={save}
            >
              {draft ? "Save new revision" : "Save draft"}
            </button>
          </div>
          {validation && (
            <div role="status" className="notice">
              <h3>
                {validation.valid
                  ? "Blueprint valid"
                  : "Blueprint needs correction"}
              </h3>
              <ul>
                {validation.diagnostics.map((item, i) => (
                  <li key={i}>{diagnosticText(item)}</li>
                ))}
              </ul>
            </div>
          )}
          <button
            disabled={locked || !draft || changed || !validation?.valid}
            onClick={() => {
              if (
                draft &&
                window.confirm(
                  `Publish saved revision ${draft.revision}? This freezes its content and policy.`,
                )
              )
                void run(() =>
                  execute({
                    kind: "publication",
                    identity: draft.id,
                    method: "POST",
                    path: `${base}/exam-blueprints/drafts/${draft.id}/publish?expected_revision=${draft.revision}`,
                  }),
                );
            }}
          >
            Publish saved revision
          </button>
        </section>
      </div>
      {preview?.content && (
        <section className="panel">
          <h2>Selected version preview</h2>
          <button className="quiet" onClick={() => setPreview(null)}>
            Close selected preview
          </button>
          <CandidatePreview
            preview={{ content: preview.content, media: preview.media }}
            base={base}
            token={token}
          />
        </section>
      )}
      {publication && (
        <>
          <PublicationSummary
            publication={publication}
            base={base}
            token={token}
          />
          <section className="panel">
            <h2>Schedule this publication</h2>
            <form onSubmit={schedule}>
              <fieldset disabled={locked}>
                <legend>New sitting</legend>
                <label>
                  Sitting title
                  <input
                    required
                    maxLength={160}
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </label>
                <label htmlFor="exam-display-zone">Display timezone</label>
                <input
                  id="exam-display-zone"
                  aria-describedby="exam-zone-help"
                  required
                  value={zone}
                  onChange={(e) => setZone(e.target.value)}
                />
                <p id="exam-zone-help" className="muted">
                  Use UTC or a fixed offset, such as UTC+05:30. Enter the times
                  below in this offset.
                </p>
                <div className="two-fields">
                  <label>
                    Opens at
                    <input
                      type="datetime-local"
                      required
                      value={opening}
                      onChange={(e) => setOpening(e.target.value)}
                    />
                  </label>
                  <label>
                    Closes at
                    <input
                      type="datetime-local"
                      required
                      value={closing}
                      onChange={(e) => setClosing(e.target.value)}
                    />
                  </label>
                </div>
                <button>Schedule sitting</button>
              </fieldset>
            </form>
          </section>
        </>
      )}
      <section className="panel">
        <h2>Sitting receipt and recovery</h2>
        <label>
          Sitting ID
          <input
            disabled={locked}
            value={sittingReference}
            onChange={(e) => setSittingReference(e.target.value)}
          />
        </label>
        <button
          className="secondary"
          disabled={locked || !sittingReference}
          onClick={() =>
            void run(async () => {
              const result = await request<Sitting>(
                `${base}/exam-sittings/${requireId(sittingReference.trim())}`,
                token,
              );
              if (active.current) setSitting(result);
            })
          }
        >
          Open sitting
        </button>
        {sitting && (
          <div role="status">
            <h3>Sitting saved</h3>
            <p>{sitting.title}</p>
            <p className="reference">Sitting: {sitting.id}</p>
            <p className="reference">Publication: {sitting.publication_id}</p>
            <p>
              {invitationTime(sitting.opens_at, sitting.display_timezone)} to{" "}
              {invitationTime(sitting.closes_at, sitting.display_timezone)} ·{" "}
              {sitting.duration_minutes} minutes base duration.
            </p>
            <p>
              This receipt describes the immutable schedule. Cancellations and
              registrations are managed separately.
            </p>
          </div>
        )}
      </section>
    </section>
  );
}
