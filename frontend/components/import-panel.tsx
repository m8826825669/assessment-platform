"use client";
import { useEffect, useState } from "react";
import { request } from "../lib/api";
import { PublicContent, Receipt } from "../lib/types";
import { CandidateItem } from "./candidate-preview";
type Report = {
  item_count: number;
  items: {
    reference: string;
    title: string;
    preview: PublicContent;
    index: number;
  }[];
};
export default function ImportPanel({
  base,
  token,
  run,
  onDirty,
}: {
  onDirty: (dirty: boolean) => void;
  base: string;
  token: string;
  run: (job: () => Promise<void>) => void;
}) {
  const [text, setText] = useState("");
  const [key, setKey] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [batch, setBatch] = useState("");
  const [busy, setBusy] = useState(false);
  const [frozen, setFrozen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  useEffect(() => {
    onDirty(!!text.trim() && !acknowledged);
  }, [text, acknowledged, onDirty]);
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
      <div className="eyebrow">Bulk authoring</div>
      <h2>Import questions as drafts</h2>
      <p>
        Internal JSON v1 · maximum 2 MiB / 50 rows / 16 media references.
        Preview is advisory; commit validates again. No approval is granted.
      </p>
      <label>
        Choose JSON file
        <input
          type="file"
          accept="application/json,.json"
          disabled={frozen || busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file)
              act(async () => {
                if (file.size > 2 * 1024 * 1024)
                  throw new Error("Import file must be no larger than 2 MiB.");
                setText(await file.text());
                setAcknowledged(false);
                setReport(null);
              });
          }}
        />
      </label>
      <label>
        Staff only · Import JSON
        <textarea
          className="code"
          spellCheck={false}
          disabled={frozen || busy}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setAcknowledged(false);
            setReport(null);
          }}
        />
      </label>
      <div className="inline">
        <button
          disabled={busy || !text || frozen}
          onClick={() =>
            act(async () => {
              if (new TextEncoder().encode(text).length > 2 * 1024 * 1024)
                throw new Error("Import exceeds 2 MiB.");
              setReport(
                await request<Report>(
                  `${base}/question-imports/preview`,
                  token,
                  { method: "POST", body: text },
                ),
              );
            })
          }
        >
          Validate preview
        </button>
      </div>
      {report && (
        <div className="notice">
          <h3>{report.item_count} valid draft(s)</h3>
          <p>Commit is all or nothing. Nothing has been created by preview.</p>
          {report.items.map((row) => (
            <details key={row.reference}>
              <summary>
                {row.reference} · {row.title}
              </summary>
              <CandidateItem content={row.preview} />
            </details>
          ))}
          <label>
            Retry key (retain until outcome is known)
            <input
              value={key}
              readOnly={frozen}
              onChange={(e) => setKey(e.target.value)}
              placeholder="Generate or enter a UUID"
            />
          </label>
          <div className="inline">
            <button
              className="secondary"
              disabled={busy || frozen}
              onClick={() => setKey(crypto.randomUUID())}
            >
              Generate retry key
            </button>
            <button
              disabled={busy || !key}
              onClick={() =>
                act(async () => {
                  setFrozen(true);
                  const result = await request<Receipt>(
                    `${base}/question-imports`,
                    token,
                    {
                      method: "POST",
                      headers: { "Idempotency-Key": key },
                      body: text,
                    },
                  );
                  setReceipt(result);
                  setAcknowledged(true);
                  setBatch(result.batch_id);
                })
              }
            >
              {frozen ? "Retry same import" : "Commit draft batch"}
            </button>
          </div>
          <p>
            After a commit attempt the document and key stay fixed, including
            after a connection failure. A retry acknowledges the original
            success. Copy the key privately if you must reload.
          </p>
        </div>
      )}
      {receipt && (
        <div className="notice success">
          <h3>Batch acknowledged · {receipt.item_count} draft(s)</h3>
          <p>Batch ID: {receipt.batch_id}</p>
          <p>
            Original creation state: {receipt.created_as}. Current question
            states may have changed.
          </p>
          <ul>
            {receipt.items.map((i) => (
              <li key={i.reference}>
                {i.reference}: {i.question_id} · version {i.version_id}
              </li>
            ))}
          </ul>
        </div>
      )}
      <label>
        Recover an owned receipt by batch ID
        <input value={batch} onChange={(e) => setBatch(e.target.value)} />
      </label>
      <button
        className="secondary"
        disabled={busy || !batch}
        onClick={() =>
          act(async () =>
            setReceipt(
              await request<Receipt>(
                `${base}/question-imports/${batch}`,
                token,
              ),
            ),
          )
        }
      >
        Load receipt
      </button>
      <p>
        <button
          className="quiet"
          disabled={busy}
          onClick={() => {
            if (
              window.confirm(
                "Start a different batch? A previous uncertain commit may already have succeeded. Retain its retry key first.",
              )
            ) {
              setFrozen(false);
              setAcknowledged(false);
              setText("");
              setKey("");
              setReport(null);
              setReceipt(null);
            }
          }}
        >
          Start a different batch
        </button>
      </p>
    </section>
  );
}
