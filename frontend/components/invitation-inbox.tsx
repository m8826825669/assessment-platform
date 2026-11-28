"use client";
import { useEffect, useRef, useState } from "react";
import { ApiError, request } from "../lib/api";
import {
  Acceptance,
  Invitation,
  InvitationPage,
  invitationTime,
  timingMessage,
} from "../lib/invitations";

export function InvitationSummary({
  invitation: row,
}: {
  invitation: Invitation;
}) {
  return (
    <>
      <h2>{row.title}</h2>
      <p className="badge">{row.window_state}</p>
      <p>{timingMessage(row)}</p>
      <dl className="invitation-facts">
        <div>
          <dt>Opens</dt>
          <dd>{invitationTime(row.opens_at, row.display_timezone)}</dd>
        </div>
        <div>
          <dt>Closes</dt>
          <dd>{invitationTime(row.closes_at, row.display_timezone)}</dd>
        </div>
        <div>
          <dt>Current allowance</dt>
          <dd>{row.allowed_minutes} minutes</dd>
        </div>
        <div>
          <dt>Current registration revision</dt>
          <dd>{row.registration_revision}</dd>
        </div>
        <div>
          <dt>Last checked by server</dt>
          <dd>{invitationTime(row.server_time, row.display_timezone)}</dd>
        </div>
      </dl>
      {row.deadline_if_started_now && (
        <p>
          A start at that check time would have a deadline of{" "}
          {invitationTime(row.deadline_if_started_now, row.display_timezone)}.
          Sitting close remains the hard limit.
        </p>
      )}
      {row.acceptance && (
        <section
          className="notice success"
          aria-label="Acknowledgement receipt"
        >
          <h3>Invitation acknowledged</h3>
          <p>
            Recorded{" "}
            {invitationTime(row.acceptance.accepted_at, row.display_timezone)}{" "}
            for registration revision {row.acceptance.registration_revision}.
          </p>
          {row.acceptance.registration_revision !==
            row.registration_revision && (
            <p>
              Your registration changed after this acknowledgement. The current
              allowance above applies.
            </p>
          )}
          <p>
            Acknowledgement does not start an exam or restore a cancelled or
            withdrawn registration.
          </p>
        </section>
      )}
    </>
  );
}

export default function InvitationInbox({
  tenant,
  token,
  onSessionExpired,
}: {
  tenant: string;
  token: string;
  onSessionExpired: () => void;
}) {
  const [page, setPage] = useState<InvitationPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<Invitation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [uncertain, setUncertain] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const errorRef = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  const active = useRef(true);
  const job = useRef(false);
  const expire = useRef(onSessionExpired);
  expire.current = onSessionExpired;
  const base = `tenants/${tenant}/exam-invitations`;
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);
  useEffect(() => {
    if (detail) detailRef.current?.focus();
  }, [detail]);
  async function perform(work: () => Promise<void>) {
    if (job.current) return;
    job.current = true;
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
        setPage(null);
        setDetail(null);
        setUncertain(null);
      }
      setError(
        problem instanceof ApiError
          ? problem
          : new Error(
              "Connection interrupted. Reload to check the server record, or retry the same acknowledgement.",
            ),
      );
    } finally {
      job.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function loadPage(nextOffset: number) {
    setDetail(null);
    setPage(null);
    const result = await request<InvitationPage>(
      `${base}?offset=${nextOffset}&limit=10`,
      token,
    );
    if (!active.current) return;
    setPage(result);
    setOffset(nextOffset);
  }
  useEffect(() => {
    void perform(() => loadPage(0));
  }, []); // keyed by tenant/session at the workspace boundary
  async function open(id: string) {
    setDetail(null);
    const result = await request<Invitation>(`${base}/${id}`, token);
    if (!active.current) return;
    setDetail(result);
    if (result.acceptance) setUncertain(null);
  }
  async function acknowledge(id: string) {
    setUncertain(id);
    let receipt: Acceptance;
    try {
      receipt = await request<Acceptance>(`${base}/${id}/accept`, token, {
        method: "POST",
        body: "{}",
      });
    } catch (problem) {
      if (active.current && problem instanceof ApiError && problem.status < 500)
        setUncertain(null);
      throw problem;
    }
    if (!active.current) return;
    setUncertain(null);
    setDetail((row) =>
      row?.registration_id === id
        ? { ...row, acceptance: receipt, can_accept: false }
        : row,
    );
    setPage(
      (old) =>
        old && {
          ...old,
          items: old.items.map((row) =>
            row.registration_id === id
              ? { ...row, acceptance: receipt, can_accept: false }
              : row,
          ),
        },
    );
    setNotice("Acknowledgement saved. Your exam has not started.");
    // Re-read current state separately: a historical receipt never proves current eligibility.
    await open(id);
  }
  return (
    <section aria-label="My invitations" aria-busy={busy}>
      <div className="page-heading">
        <div>
          <div className="eyebrow">Candidate workspace</div>
          <h1>My invitations</h1>
          <p>
            View your registrations and the latest timing provided by your
            institution.
          </p>
        </div>
        <button
          className="secondary"
          disabled={busy}
          onClick={() =>
            void perform(() =>
              detail ? open(detail.registration_id) : loadPage(offset),
            )
          }
        >
          Refresh invitations
        </button>
      </div>
      <p className="notice">
        Acknowledgement is optional. It does not begin an exam or run a timer.
        Refresh to check current availability.
      </p>
      {error && (
        <div
          className="notice error"
          role="alert"
          aria-label="Invitation request error"
          tabIndex={-1}
          ref={errorRef}
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
      {uncertain && (
        <div className="notice" role="status">
          <p>
            The acknowledgement outcome is unconfirmed. Retrying the same
            registration safely retrieves any saved receipt.
          </p>
          <button
            disabled={busy}
            onClick={() => void perform(() => acknowledge(uncertain))}
          >
            Retry same acknowledgement
          </button>
        </div>
      )}
      {detail ? (
        <section
          className="panel invitation-detail"
          ref={detailRef}
          tabIndex={-1}
          aria-label="Invitation details"
        >
          <button
            className="quiet"
            disabled={busy || !!uncertain}
            onClick={() => void perform(() => loadPage(offset))}
          >
            Back to invitations
          </button>
          <InvitationSummary invitation={detail} />
          {!detail.acceptance && detail.can_accept && !uncertain && (
            <button
              disabled={busy}
              onClick={() =>
                void perform(() => acknowledge(detail.registration_id))
              }
            >
              Acknowledge invitation
            </button>
          )}
          {!detail.acceptance && !detail.can_accept && (
            <p>New acknowledgement is unavailable for this registration.</p>
          )}
          <details>
            <summary>Registration references</summary>
            <dl>
              <dt>Registration</dt>
              <dd>{detail.registration_id}</dd>
              <dt>Sitting</dt>
              <dd>{detail.sitting_id}</dd>
            </dl>
          </details>
        </section>
      ) : (
        page && (
          <>
            {page.items.length === 0 ? (
              <section className="panel">
                <h2>No invitations on this page</h2>
                <p>
                  Your institution will register you when a sitting is ready.
                  You can refresh or check another institution.
                </p>
              </section>
            ) : (
              <ul className="invitation-list">
                {page.items.map((row) => (
                  <li className="panel" key={row.registration_id}>
                    <h2>{row.title}</h2>
                    <p className="badge">{row.window_state}</p>
                    <p>
                      {invitationTime(row.opens_at, row.display_timezone)} ·{" "}
                      {row.allowed_minutes} minutes
                    </p>
                    <p>
                      {row.acceptance ? "Acknowledged" : "Not acknowledged"}
                    </p>
                    <button
                      className="secondary"
                      aria-label={`View invitation: ${row.title}`}
                      disabled={busy || !!uncertain}
                      onClick={() =>
                        void perform(() => open(row.registration_id))
                      }
                    >
                      View invitation
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="inline" aria-label="Invitation pages">
              <button
                className="secondary"
                disabled={busy || !!uncertain || offset === 0}
                onClick={() =>
                  void perform(() => loadPage(Math.max(0, offset - 10)))
                }
              >
                Previous invitations
              </button>
              <span>Page {Math.floor(offset / 10) + 1}</span>
              <button
                className="secondary"
                disabled={busy || !!uncertain || !page.has_more}
                onClick={() => void perform(() => loadPage(offset + 10))}
              >
                Next invitations
              </button>
            </div>
          </>
        )
      )}
    </section>
  );
}
