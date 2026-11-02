"use client";
import { useState } from "react";
import { request } from "../lib/api";
import { Term, label } from "../lib/types";
export default function TaxonomyPanel({
  base,
  token,
  terms,
  manage,
  run,
  reload,
}: {
  base: string;
  token: string;
  terms: Term[];
  manage: boolean;
  run: (job: () => Promise<void>) => void;
  reload: () => Promise<void>;
}) {
  const [kind, setKind] = useState("subject");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Term | null>(null);
  const [rename, setRename] = useState("");
  const act = (job: () => Promise<void>) =>
    run(async () => {
      setBusy(true);
      try {
        await job();
      } finally {
        setBusy(false);
      }
    });
  return (
    <section className="panel">
      <div className="eyebrow">Institution catalogue</div>
      <h2>Subjects, topics & outcomes</h2>
      <p>
        Saved question versions retain their historical labels. Retired terms
        cannot be assigned to new versions.
      </p>
      {manage && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act(async () => {
              await request(`${base}/taxonomy`, token, {
                method: "POST",
                body: JSON.stringify({
                  kind,
                  code,
                  label: name,
                  parent_id: kind === "topic" ? parent : null,
                }),
              });
              setName("");
              setCode("");
              await reload();
            });
          }}
        >
          <div className="form-grid">
            <label>
              Term kind
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {["subject", "topic", "outcome", "tag"].map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </label>
            <label>
              Stable code
              <input
                required
                pattern="[a-z][a-z0-9_-]{0,63}"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
            <label>
              Display label
              <input
                required
                maxLength={200}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            {kind === "topic" && (
              <label>
                Parent subject
                <select
                  required
                  value={parent}
                  onChange={(e) => setParent(e.target.value)}
                >
                  <option value="">Choose subject</option>
                  {terms
                    .filter((t) => t.kind === "subject" && t.state === "active")
                    .map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.label}
                      </option>
                    ))}
                </select>
              </label>
            )}
          </div>
          <button disabled={busy}>Create term</button>
        </form>
      )}
      <ul className="term-list">
        {terms.map((t) => (
          <li key={t.id}>
            <span>
              <strong>{t.label}</strong>{" "}
              <small>
                {label(t.kind)} · {t.code} · {t.state}
              </small>
            </span>
            {manage && t.state === "active" && (
              <button
                className="quiet"
                onClick={() => {
                  setSelected(t);
                  setRename(t.label);
                }}
              >
                Manage {t.code}
              </button>
            )}
          </li>
        ))}
      </ul>
      {selected && (
        <div className="notice">
          <h3>Manage {selected.code}</h3>
          <label>
            New display label
            <input value={rename} onChange={(e) => setRename(e.target.value)} />
          </label>
          <div className="inline">
            <button
              disabled={busy || !rename.trim()}
              onClick={() =>
                act(async () => {
                  await request(`${base}/taxonomy/${selected.id}`, token, {
                    method: "PATCH",
                    body: JSON.stringify({
                      expected_revision: selected.revision,
                      label: rename,
                    }),
                  });
                  setSelected(null);
                  await reload();
                })
              }
            >
              Save label
            </button>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    "Retire this term? Existing version labels are preserved.",
                  )
                )
                  act(async () => {
                    await request(`${base}/taxonomy/${selected.id}`, token, {
                      method: "PATCH",
                      body: JSON.stringify({
                        expected_revision: selected.revision,
                        state: "retired",
                      }),
                    });
                    setSelected(null);
                    await reload();
                  });
              }}
            >
              Retire term
            </button>
            <button className="quiet" onClick={() => setSelected(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
