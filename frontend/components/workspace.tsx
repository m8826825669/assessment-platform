"use client";
import { FormEvent, useEffect, useRef, useState } from "react";
import { ApiError, request } from "../lib/api";
import {
  Access,
  Content,
  Detail,
  Institution,
  Media,
  Preview,
  Row,
  Term,
  Kind,
  kinds,
  label,
  newContent,
} from "../lib/types";
import { ContentEditor } from "./content-editor";
import CandidatePreview from "./candidate-preview";
import MediaPanel from "./media-panel";
import ImportPanel from "./import-panel";
import TaxonomyPanel from "./taxonomy-panel";
type View = "bank" | "review" | "approved" | "imports" | "taxonomy";
export default function Workspace() {
  const [token, setToken] = useState("");
  const tokenRef = useRef("");
  const generation = useRef(0);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  const [tenant, setTenant] = useState("");
  const [access, setAccess] = useState<Access | null>(null);
  const [view, setView] = useState<View>("bank");
  const [rows, setRows] = useState<Row[]>([]);
  const [terms, setTerms] = useState<Term[]>([]);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [state, setState] = useState("");
  const [filterTerm, setFilterTerm] = useState("");
  const [filter, setFilter] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState<Content>(newContent("single_choice"));
  const [taxonomy, setTaxonomy] = useState<string[]>([]);
  const [media, setMedia] = useState<Media[]>([]);
  const [dirty, setDirty] = useState(false);
  const [importDirty, setImportDirty] = useState(false);
  const [history, setHistory] = useState<Row[]>([]);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(0);
  const [error, setError] = useState<Error | null>(null);
  const [notice, setNotice] = useState("");
  const errorRef = useRef<HTMLDivElement>(null);
  const base = `tenants/${tenant}`;
  const write = access?.permissions.includes("questions.write") ?? false;
  const review = access?.permissions.includes("questions.review") ?? false;
  const select = access?.permissions.includes("exams.manage") ?? false;
  function clearSession() {
    generation.current++;
    tokenRef.current = "";
    setToken("");
    setInstitutions([]);
    setTenant("");
    setAccess(null);
    setRows([]);
    setTerms([]);
    setDetail(null);
    setEditing(false);
    setPreview(null);
    setHistory([]);
    setTitle("");
    setContent(newContent("single_choice"));
    setMedia([]);
    setTaxonomy([]);
    setDirty(false);
    setImportDirty(false);
    setPassword("");
  }
  const jobs = useRef(0);
  function run(job: () => Promise<void>) {
    jobs.current++;
    setPending(jobs.current);
    setError(null);
    setNotice("");
    void job()
      .catch((e) => {
        const problem = e instanceof Error ? e : new Error("Request failed");
        if (
          problem instanceof ApiError &&
          problem.status === 401 &&
          tokenRef.current
        ) {
          clearSession();
          setNotice(
            "Your session ended. Sign in again. Private workspace state was cleared.",
          );
        } else setError(problem);
      })
      .finally(() => {
        jobs.current--;
        setPending(jobs.current);
      });
  }
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty || importDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty, importDirty]);
  function canLeave() {
    return (
      (!dirty && !importDirty) ||
      window.confirm(
        "Discard unsaved work? Retain an uncertain import retry key and copy your changes first.",
      )
    );
  }
  function resetEditor() {
    setImportDirty(false);
    setEditing(false);
    setDetail(null);
    setPreview(null);
    setHistory([]);
    setHistoryOffset(0);
    setDirty(false);
    setReason("");
    setTitle("");
    setContent(newContent("single_choice"));
    setTaxonomy([]);
    setMedia([]);
  }
  async function loadTerms(t = tenant, auth = token) {
    const gen = generation.current;
    let all: Term[] = [];
    for (let page = 0; ; page += 200) {
      const batch = await request<Term[]>(
        `tenants/${t}/taxonomy?state=active&offset=${page}&limit=200`,
        auth,
      );
      all = all.concat(batch);
      if (batch.length < 200) break;
      if (page >= 9800) break;
    }
    if (gen === generation.current) setTerms(all);
  }
  async function loadRows() {
    if (!tenant || !access) return;
    const gen = generation.current;
    const endpoint =
      view === "review"
        ? "question-reviews"
        : view === "approved"
          ? "question-selections"
          : "questions";
    const result = await request<Row[]>(
      `${base}/${endpoint}?offset=${offset}&limit=20${filter}`,
      token,
    );
    if (gen === generation.current) setRows(result);
  }
  useEffect(() => {
    if (token && access && ["bank", "review", "approved"].includes(view))
      run(loadRows);
  }, [tenant, access, view, offset, filter]); // scoped collection; current generation discards late responses
  async function chooseTenant(id: string, auth = token) {
    generation.current++;
    resetEditor();
    setRows([]);
    setTerms([]);
    setTenant(id);
    setAccess(null);
    setOffset(0);
    setFilter("");
    setQuery("");
    setKind("");
    setState("");
    setFilterTerm("");
    const gen = generation.current;
    const a = await request<Access>(`tenants/${id}/access`, auth);
    if (gen !== generation.current) return;
    setAccess(a);
    setView(
      a.permissions.includes("questions.write")
        ? "bank"
        : a.permissions.includes("questions.review")
          ? "review"
          : "approved",
    );
    if (a.permissions.includes("taxonomy.read")) await loadTerms(id, auth);
  }
  async function login(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const result = await request<{ access_token: string }>("auth/login", "", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      tokenRef.current = result.access_token;
      setToken(result.access_token);
      setPassword("");
      const list = await request<Institution[]>(
        "auth/institutions",
        result.access_token,
      );
      setInstitutions(list);
      if (list.length)
        await chooseTenant(list[0].tenant_id, result.access_token);
    } finally {
      setBusy(false);
      setPassword("");
    }
  }
  async function open(row: Row) {
    if (!canLeave()) return;
    setBusy(true);
    try {
      setPreview(null);
      setReason("");
      if (view === "approved") {
        const selected = await request<Row>(
          `${base}/question-selections/${row.version_id}`,
          token,
        );
        setDetail(null);
        setEditing(false);
        setPreview({ content: selected.content!, media: selected.media });
        return;
      }
      const d = await request<Detail>(
        view === "review"
          ? `${base}/question-reviews/${row.question_id}/versions/${row.version_id}`
          : `${base}/questions/${row.question_id}`,
        token,
      );
      setDetail(d);
      setTitle(d.title);
      setContent(d.content);
      setTaxonomy(d.taxonomy.map((t) => t.id));
      setMedia(d.media);
      setDirty(false);
      setEditing(view === "bank");
      setHistoryOffset(0);
      setHistory([]);
      if (view === "bank")
        setHistory(
          await request<Row[]>(
            `${base}/questions/${row.question_id}/versions?limit=20`,
            token,
          ),
        );
    } finally {
      setBusy(false);
    }
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const saved = await request<Detail>(
        detail
          ? `${base}/questions/${detail.question_id}/versions`
          : `${base}/questions`,
        token,
        {
          method: "POST",
          body: JSON.stringify({
            title,
            content,
            taxonomy_ids: taxonomy,
            media_ids: media.map((m) => m.asset_id),
            ...(detail ? { expected_revision: detail.revision } : {}),
          }),
        },
      );
      setDetail(saved);
      setContent(saved.content);
      setDirty(false);
      setPreview(null);
      setNotice(`Saved immutable version ${saved.version_number}.`);
      await loadRows();
      setHistory(
        await request<Row[]>(
          `${base}/questions/${saved.question_id}/versions?limit=20`,
          token,
        ),
      );
    } finally {
      setBusy(false);
    }
  }
  async function loadPreview(version = detail?.version_id) {
    if (!detail || !version) return;
    const gen = generation.current;
    const result = await request<Preview>(
      view === "review"
        ? `${base}/question-reviews/${detail.question_id}/versions/${version}/preview`
        : `${base}/questions/${detail.question_id}/preview?version_id=${version}`,
      token,
    );
    if (gen === generation.current) setPreview(result);
  }
  async function decision(action: string) {
    if (!detail) return;
    setBusy(true);
    try {
      const updated = await request<Detail>(
        `${base}/question-reviews/${detail.question_id}/versions/${detail.version_id}`,
        token,
        {
          method: "POST",
          body: JSON.stringify({
            action,
            expected_revision: detail.revision,
            expected_review_revision: detail.review_revision,
            content_hash: detail.content_hash,
            ...(["return", "retire"].includes(action) ? { reason } : {}),
          }),
        },
      );
      setDetail(updated);
      setHistory((rows) =>
        rows.map((row) =>
          row.version_id === updated.version_id
            ? {
                ...row,
                state: updated.state,
                review_revision: updated.review_revision,
              }
            : row,
        ),
      );
      setReason("");
      setNotice(
        `Version ${action === "submit" ? "submitted for independent review" : action === "approve" ? "approved" : action === "return" ? "returned with feedback" : "retired"}.`,
      );
      await loadRows();
    } finally {
      setBusy(false);
    }
  }
  function nav(next: View) {
    if (busy || jobs.current || next === view) return;
    if (canLeave()) {
      generation.current++;
      resetEditor();
      setView(next);
      setOffset(0);
      setFilter("");
      setQuery("");
      setKind("");
      setState("");
      setFilterTerm("");
      setRows([]);
      setError(null);
      setNotice("");
    }
  }
  const errorBox = error && (
    <div
      className="error"
      role="alert"
      aria-label="Workspace error"
      tabIndex={-1}
      ref={errorRef}
    >
      <strong>{error.message}</strong>
      {error instanceof ApiError && (
        <>
          <p>
            Code: {error.code}{" "}
            {error.requestId && `· Request: ${error.requestId}`}
          </p>
          {error.locations.length > 0 && (
            <ul>
              {error.locations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          )}
          {error.status === 409 && detail && (
            <p>
              Your form was retained. Compare your work before choosing “Reload
              current version”.
            </p>
          )}
        </>
      )}
    </div>
  );
  if (!token)
    return (
      <main id="main" className="login-page">
        <div className="login-story">
          <span className="brand-mark">A</span>
          <div className="eyebrow">Assessment workspace</div>
          <h1>
            Good assessments
            <br />
            begin with
            <br />
            <em>good questions.</em>
          </h1>
          <p>
            A governed bank. Independent review.
            <br />
            Every version preserved.
          </p>
          <div className="login-foot">INSTITUTION PORTAL · QUESTION BANK</div>
        </div>
        <div className="login-form">
          <div className="eyebrow">Staff access</div>
          <h2>Welcome back</h2>
          <p>Sign in with your institution account.</p>
          {errorBox}
          {notice && <p role="status">{notice}</p>}
          <form onSubmit={(e) => run(() => login(e))}>
            <label>
              Email address
              <input
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label>
              Password
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <button disabled={busy}>
              {busy ? "Signing in…" : "Sign in to workspace →"}
            </button>
          </form>
          <p className="muted">
            Access is provisioned by your administrator.
            <br />
            Reloading this page requires signing in again.
          </p>
        </div>
      </main>
    );
  return (
    <div className="workspace">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">A</span>
          <span>
            assessment<small>INSTITUTION WORKSPACE</small>
          </span>
        </div>
        <label className="institution-label">
          Institution
          <select
            aria-label="Institution"
            value={tenant}
            disabled={busy}
            onChange={(e) => {
              if (!jobs.current && canLeave())
                run(() => chooseTenant(e.target.value));
            }}
          >
            {institutions.map((i) => (
              <option key={i.tenant_id} value={i.tenant_id}>
                {i.institution_name}
              </option>
            ))}
          </select>
        </label>
        <div className="nav-heading">CONTENT WORKSPACE</div>
        <nav aria-label="Workspace">
          {write && (
            <button
              disabled={busy || pending > 0}
              aria-current={view === "bank" ? "page" : undefined}
              onClick={() => nav("bank")}
            >
              <span aria-hidden="true">▦</span>Question bank
            </button>
          )}
          {review && (
            <button
              disabled={busy || pending > 0}
              aria-current={view === "review" ? "page" : undefined}
              onClick={() => nav("review")}
            >
              <span aria-hidden="true">◉</span>Review queue
            </button>
          )}
          {select && (
            <button
              disabled={busy || pending > 0}
              aria-current={view === "approved" ? "page" : undefined}
              onClick={() => nav("approved")}
            >
              <span aria-hidden="true">✓</span>Approved versions
            </button>
          )}
          {write && (
            <button
              disabled={busy || pending > 0}
              aria-current={view === "imports" ? "page" : undefined}
              onClick={() => nav("imports")}
            >
              <span aria-hidden="true">↥</span>Import questions
            </button>
          )}
          {access?.permissions.includes("taxonomy.read") && (
            <button
              disabled={busy || pending > 0}
              aria-current={view === "taxonomy" ? "page" : undefined}
              onClick={() => nav("taxonomy")}
            >
              <span aria-hidden="true">⌘</span>Taxonomy
            </button>
          )}
        </nav>
        <div className="sidebar-note">
          <strong>Built for trust.</strong>
          <p>
            Approval belongs to an exact version. Editing creates a new draft.
          </p>
        </div>
        <div className="session">
          <span className="avatar">
            {access?.role.slice(0, 1).toUpperCase()}
          </span>
          <span>
            {label(access?.role ?? "staff")}
            <small>Institution access</small>
          </span>
          <button
            className="signout"
            disabled={busy || pending > 0}
            onClick={() => {
              if (!busy && !jobs.current && canLeave())
                run(async () => {
                  try {
                    await request("auth/logout", token, { method: "POST" });
                  } finally {
                    clearSession();
                  }
                });
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main id="main" className="main">
        <header className="topbar">
          <span>
            Workspace <span className="muted">/</span>{" "}
            <strong>
              {view === "bank"
                ? "Question bank"
                : view === "review"
                  ? "Independent review"
                  : view === "approved"
                    ? "Approved versions"
                    : label(view)}
            </strong>
          </span>
          <span className="environment">
            <span /> Authoring workspace
          </span>
        </header>
        <div className="page-content">
          {errorBox}
          {notice && (
            <div className="notice success" role="status">
              {notice}
            </div>
          )}
          {!access ? (
            <p role="status">Loading institution…</p>
          ) : !write && !review && !select ? (
            <section className="panel">
              <h1>Question bank access unavailable</h1>
              <p>
                Your current role does not grant authoring, review or selection
                access. Contact your institution administrator.
              </p>
            </section>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    {
                      institutions.find((i) => i.tenant_id === tenant)
                        ?.institution_name
                    }
                  </div>
                  <h1>
                    {view === "bank"
                      ? "Your question bank"
                      : view === "review"
                        ? "Independent review"
                        : view === "approved"
                          ? "Ready for assessment"
                          : view === "imports"
                            ? "Bring your questions in"
                            : "Organize your bank"}
                  </h1>
                  <p>
                    {view === "bank"
                      ? "Create with care. Review independently. Preserve every version."
                      : view === "review"
                        ? "Review the exact content, marking rules and accessible media before deciding."
                        : view === "approved"
                          ? "Candidate-safe snapshots of approved, non-retired versions."
                          : "Governed content, within your institution."}
                  </p>
                </div>
                {view === "bank" && (
                  <button
                    disabled={busy}
                    onClick={() => {
                      if (canLeave()) {
                        resetEditor();
                        setEditing(true);
                        setDirty(true);
                      }
                    }}
                  >
                    + New question
                  </button>
                )}
              </div>
              {view === "imports" ? (
                <ImportPanel
                  onDirty={setImportDirty}
                  key={tenant}
                  base={base}
                  token={token}
                  run={run}
                />
              ) : view === "taxonomy" ? (
                <TaxonomyPanel
                  key={tenant}
                  base={base}
                  token={token}
                  terms={terms}
                  manage={access.permissions.includes("taxonomy.manage")}
                  run={run}
                  reload={() => loadTerms()}
                />
              ) : (
                <>
                  <section className="bank-panel">
                    <form
                      className="filters"
                      onSubmit={(e) => {
                        e.preventDefault();
                        if (!canLeave()) return;
                        resetEditor();
                        const params = new URLSearchParams();
                        if (query.trim()) params.set("q", query.trim());
                        if (kind) params.set("kind", kind);
                        if (state && view !== "approved")
                          params.set("state", state);
                        if (filterTerm)
                          params.append("taxonomy_ids", filterTerm);
                        setOffset(0);
                        setFilter(params.size ? "&" + params : "");
                      }}
                    >
                      <label className="search">
                        Search titles
                        <input
                          type="search"
                          placeholder="Find a question…"
                          maxLength={160}
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                        />
                      </label>
                      <label>
                        Type
                        <select
                          value={kind}
                          onChange={(e) => setKind(e.target.value)}
                        >
                          <option value="">All types</option>
                          {kinds.map((k) => (
                            <option key={k} value={k}>
                              {label(k)}
                            </option>
                          ))}
                        </select>
                      </label>
                      {view === "bank" && (
                        <label>
                          State
                          <select
                            value={state}
                            onChange={(e) => setState(e.target.value)}
                          >
                            <option value="">All states</option>
                            {[
                              "draft",
                              "in_review",
                              "returned",
                              "approved",
                              "retired",
                              "superseded",
                            ].map((s) => (
                              <option key={s} value={s}>
                                {label(s)}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                      <label>
                        Classification
                        <select
                          value={filterTerm}
                          onChange={(e) => setFilterTerm(e.target.value)}
                        >
                          <option value="">All classifications</option>
                          {terms.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button className="secondary" disabled={busy}>
                        Apply
                      </button>
                    </form>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th scope="col">Question / version</th>
                            <th scope="col">Classification</th>
                            <th scope="col">State</th>
                            <th scope="col">Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((r) => (
                            <tr key={r.version_id}>
                              <td>
                                <strong>{r.title}</strong>
                                <small>
                                  {r.version_number
                                    ? `Version ${r.version_number}`
                                    : r.version_id}
                                </small>
                              </td>
                              <td>
                                {r.taxonomy.length ? (
                                  r.taxonomy.map((t) => (
                                    <span className="tag" key={t.id}>
                                      {t.label}
                                    </span>
                                  ))
                                ) : (
                                  <span className="muted">Unclassified</span>
                                )}
                              </td>
                              <td>
                                <span
                                  className={`badge ${r.state ?? "approved"}`}
                                >
                                  {label(r.state ?? "approved")}
                                </span>
                              </td>
                              <td>
                                <button
                                  className="quiet"
                                  aria-label={`${view === "review" ? "Review" : view === "approved" ? "Preview" : "Open"} ${r.title}`}
                                  disabled={busy}
                                  onClick={() => run(() => open(r))}
                                >
                                  {view === "review"
                                    ? "Review"
                                    : view === "approved"
                                      ? "Preview"
                                      : "Open"}
                                  <span aria-hidden="true"> →</span>
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {!rows.length && (
                      <div className="empty">
                        <span>◇</span>
                        <h3>
                          {view === "bank"
                            ? "A thoughtful bank starts here"
                            : "No matching versions"}
                        </h3>
                        <p>
                          {view === "bank"
                            ? "Create a question or import your existing content. New content always begins as a draft."
                            : "Refresh or adjust the filters. Only versions allowed by your current role appear."}
                        </p>
                      </div>
                    )}
                    <footer className="table-footer">
                      <span>
                        Showing {offset + (rows.length ? 1 : 0)}–
                        {offset + rows.length} · 20 per page
                      </span>
                      <div className="inline">
                        <button
                          className="quiet"
                          disabled={busy || offset === 0}
                          onClick={() => setOffset(Math.max(0, offset - 20))}
                        >
                          Previous
                        </button>
                        <button
                          className="quiet"
                          disabled={busy || rows.length < 20}
                          onClick={() => setOffset(offset + 20)}
                        >
                          Next
                        </button>
                        <button
                          className="quiet"
                          disabled={busy}
                          onClick={() => run(loadRows)}
                        >
                          Refresh list
                        </button>
                      </div>
                    </footer>
                  </section>
                  {(editing || detail) && (
                    <div className="editor-layout">
                      <section className="panel editor">
                        <div className="section-heading">
                          <h2>
                            {detail
                              ? `Version ${detail.version_number} · ${label(detail.state ?? "draft")}`
                              : "New question"}
                          </h2>
                          <span className="badge">
                            {dirty ? "Unsaved changes" : "Saved snapshot"}
                          </span>
                        </div>
                        {editing ? (
                          <form onSubmit={(e) => run(() => save(e))}>
                            <fieldset disabled={busy}>
                              <label>
                                Question title
                                <input
                                  required
                                  maxLength={200}
                                  value={title}
                                  onChange={(e) => {
                                    setTitle(e.target.value);
                                    setDirty(true);
                                  }}
                                />
                              </label>
                              <ContentEditor
                                value={content}
                                onChange={(c) => {
                                  setContent(c);
                                  setDirty(true);
                                }}
                              />
                              <fieldset>
                                <legend>Classification</legend>
                                <p>
                                  Choose active terms. Topic subjects are
                                  included automatically.
                                </p>
                                {[
                                  ...terms,
                                  ...(detail?.taxonomy.filter(
                                    (t) => !terms.some((x) => x.id === t.id),
                                  ) ?? []),
                                ].map((t) => (
                                  <label className="check" key={t.id}>
                                    <input
                                      type="checkbox"
                                      checked={taxonomy.includes(t.id)}
                                      onChange={(e) => {
                                        setTaxonomy(
                                          e.target.checked
                                            ? [...taxonomy, t.id]
                                            : taxonomy.filter(
                                                (id) => id !== t.id,
                                              ),
                                        );
                                        setDirty(true);
                                      }}
                                    />
                                    {t.label}{" "}
                                    <small>
                                      {t.kind}
                                      {t.state === "retired" ||
                                      !terms.some((x) => x.id === t.id)
                                        ? " · retired; remove before saving"
                                        : ""}
                                    </small>
                                  </label>
                                ))}
                              </fieldset>
                              <fieldset>
                                <legend>Attached images</legend>
                                {media.length ? (
                                  media.map((m) => (
                                    <div
                                      className="attachment"
                                      key={m.asset_id}
                                    >
                                      <span>{m.description}</span>
                                      <button
                                        type="button"
                                        className="quiet"
                                        onClick={() => {
                                          setMedia(
                                            media.filter(
                                              (a) => a.asset_id !== m.asset_id,
                                            ),
                                          );
                                          setDirty(true);
                                        }}
                                      >
                                        Remove attachment
                                      </button>
                                    </div>
                                  ))
                                ) : (
                                  <p>No images attached.</p>
                                )}
                              </fieldset>
                              <div className="sticky-actions">
                                <span>
                                  Every save creates an immutable draft version.
                                </span>
                                <button disabled={busy || (!dirty && !!detail)}>
                                  {busy ? "Saving…" : "Save draft"}
                                </button>
                              </div>
                            </fieldset>
                          </form>
                        ) : (
                          <div className="private">
                            <h3>Staff only · Saved marking material</h3>
                            <p>Inspect all fields before independent review.</p>
                            <pre>
                              {JSON.stringify(detail?.content, null, 2)}
                            </pre>
                          </div>
                        )}
                        {detail && (
                          <section className="review-actions">
                            <h3>Version workflow</h3>
                            <p>
                              Current root revision {detail.revision} · review
                              sequence {detail.review_revision}. Approval never
                              transfers to a new draft.
                            </p>
                            <div className="inline">
                              {editing && detail.state === "draft" && (
                                <button
                                  disabled={busy || dirty}
                                  onClick={() => run(() => decision("submit"))}
                                >
                                  Submit for review
                                </button>
                              )}
                              {review && detail.state === "in_review" && (
                                <button
                                  disabled={busy}
                                  onClick={() => run(() => decision("approve"))}
                                >
                                  Approve exact version
                                </button>
                              )}
                              <button
                                className="secondary"
                                disabled={busy || dirty}
                                onClick={() =>
                                  run(async () => {
                                    const d = await request<Detail>(
                                      `${base}/question-reviews/${detail.question_id}/versions/${detail.version_id}`,
                                      token,
                                    );
                                    setDetail(d);
                                  })
                                }
                              >
                                Load review feedback
                              </button>
                              <button
                                className="secondary"
                                disabled={busy}
                                onClick={() => {
                                  if (canLeave()) run(() => open(detail));
                                }}
                              >
                                Reload current version
                              </button>
                            </div>
                            {((review && detail.state === "in_review") ||
                              (review && detail.state === "approved")) && (
                              <>
                                <label>
                                  Staff only · Reason (required for return or
                                  retirement)
                                  <textarea
                                    value={reason}
                                    maxLength={1000}
                                    onChange={(e) => setReason(e.target.value)}
                                  />
                                </label>
                                <button
                                  className="secondary"
                                  disabled={busy || !reason.trim()}
                                  onClick={() =>
                                    run(() =>
                                      decision(
                                        detail.state === "approved"
                                          ? "retire"
                                          : "return",
                                      ),
                                    )
                                  }
                                >
                                  {detail.state === "approved"
                                    ? "Retire approved version"
                                    : "Return with feedback"}
                                </button>
                              </>
                            )}
                            {detail.decisions?.map((d) => (
                              <div className="decision" key={d.id}>
                                <strong>
                                  {label(d.action)} · sequence {d.sequence}
                                </strong>
                                <p>{d.reason ?? "No written feedback"}</p>
                              </div>
                            ))}
                          </section>
                        )}
                      </section>
                      <aside className="editor-side">
                        {editing && (
                          <MediaPanel
                            key={tenant}
                            base={base}
                            token={token}
                            run={run}
                            onAttach={(asset) => {
                              if (media.length >= 16) {
                                setError(
                                  new Error(
                                    "At most 16 media attachments are allowed.",
                                  ),
                                );
                                return;
                              }
                              setMedia([
                                ...media.filter(
                                  (m) => m.asset_id !== asset.asset_id,
                                ),
                                asset,
                              ]);
                              setDirty(true);
                            }}
                          />
                        )}
                        <section className="panel">
                          <h3>Candidate rendering</h3>
                          <p>
                            The server supplies only the allowed fields for this
                            saved version. Save changes before previewing them.
                          </p>
                          <button
                            className="secondary"
                            disabled={!detail || busy || dirty}
                            onClick={() => run(() => loadPreview())}
                          >
                            Preview saved version
                          </button>
                        </section>
                        {history.length > 0 && (
                          <section className="panel">
                            <h3>Immutable version history</h3>
                            {history.map((h) => (
                              <div className="history-row" key={h.version_id}>
                                <strong>Version {h.version_number}</strong>
                                <span className="badge">
                                  {label(h.state ?? "draft")}
                                </span>
                                <button
                                  className="quiet"
                                  disabled={busy}
                                  onClick={() =>
                                    run(() => loadPreview(h.version_id))
                                  }
                                >
                                  Preview version {h.version_number}
                                </button>
                                <button
                                  className="quiet"
                                  disabled={busy}
                                  onClick={() => {
                                    if (canLeave())
                                      run(async () => {
                                        const saved = await request<Detail>(
                                          `${base}/question-reviews/${h.question_id}/versions/${h.version_id}`,
                                          token,
                                        );
                                        setDetail(saved);
                                        setEditing(false);
                                        setDirty(false);
                                        setPreview(null);
                                      });
                                  }}
                                >
                                  Inspect version {h.version_number}
                                </button>
                              </div>
                            ))}
                            <div className="inline">
                              <button
                                className="quiet"
                                disabled={historyOffset === 0 || busy}
                                onClick={() =>
                                  run(async () => {
                                    const next = Math.max(
                                      0,
                                      historyOffset - 20,
                                    );
                                    setHistory(
                                      await request<Row[]>(
                                        `${base}/questions/${detail!.question_id}/versions?limit=20&offset=${next}`,
                                        token,
                                      ),
                                    );
                                    setHistoryOffset(next);
                                  })
                                }
                              >
                                Earlier page
                              </button>
                              <button
                                className="quiet"
                                disabled={history.length < 20 || busy}
                                onClick={() =>
                                  run(async () => {
                                    const next = historyOffset + 20;
                                    setHistory(
                                      await request<Row[]>(
                                        `${base}/questions/${detail!.question_id}/versions?limit=20&offset=${next}`,
                                        token,
                                      ),
                                    );
                                    setHistoryOffset(next);
                                  })
                                }
                              >
                                Next page
                              </button>
                            </div>
                          </section>
                        )}
                      </aside>
                    </div>
                  )}
                  {preview && (
                    <section className="preview-section">
                      <div className="section-heading">
                        <h2>Candidate preview</h2>
                        <button
                          className="quiet"
                          onClick={() => setPreview(null)}
                        >
                          Close preview
                        </button>
                      </div>
                      <CandidatePreview
                        key={preview.version_id ?? "selected"}
                        preview={preview}
                        base={base}
                        token={token}
                      />
                    </section>
                  )}
                </>
              )}
            </>
          )}
          <footer className="page-footer">
            Assessment platform · Governed question bank{" "}
            <span>P2 · Authoring & review</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
