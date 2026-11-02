"use client";
import { useEffect, useState } from "react";
import { imageBytes } from "../lib/api";
import { Preview, PublicContent, Media, label } from "../lib/types";
function ProtectedImage({
  asset,
  base,
  token,
}: {
  asset: Media;
  base: string;
  token: string;
}) {
  const [url, setUrl] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    let objectUrl = "";
    setUrl("");
    setFailed(false);
    imageBytes(`${base}/media/${asset.asset_id}/content`, token, abort.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        if (!abort.signal.aborted) setUrl(objectUrl);
        else URL.revokeObjectURL(objectUrl);
      })
      .catch(() => {
        if (!abort.signal.aborted) setFailed(true);
      });
    return () => {
      abort.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [asset.asset_id, base, token]);
  return (
    <figure>
      {url ? (
        <img
          src={url}
          alt={asset.description}
          width={asset.width ?? undefined}
          height={asset.height ?? undefined}
        />
      ) : (
        <p role="status">
          {failed
            ? "Protected image unavailable. Retry after checking services."
            : "Loading protected image…"}
        </p>
      )}
      <figcaption>{asset.description}</figcaption>
    </figure>
  );
}
export function CandidateItem({ content }: { content: PublicContent }) {
  return (
    <section className="candidate-item">
      <div className="eyebrow">
        {label(content.kind)} · {content.points} points
      </div>
      <p className="prompt">{content.prompt}</p>
      {content.kind === "passage_group" && (
        <>
          <blockquote>{content.passage}</blockquote>
          {content.children?.map((c) => (
            <CandidateItem key={c.item_id} content={c} />
          ))}
        </>
      )}
      {content.options && (
        <fieldset>
          <legend>Your answer</legend>
          {content.options.map((o) => (
            <label className="answer-option" key={o.id}>
              <input
                type={content.kind === "single_choice" ? "radio" : "checkbox"}
                name={content.item_id}
                value={o.id}
              />
              {o.text}
            </label>
          ))}
        </fieldset>
      )}
      {content.kind === "numeric" && (
        <label>
          Your numeric answer {content.unit_label && `(${content.unit_label})`}
          <input inputMode="decimal" />
        </label>
      )}
      {(content.kind === "short_answer" || content.kind === "essay") && (
        <label>
          Your answer
          <textarea maxLength={content.max_response_characters} />
          <small>Up to {content.max_response_characters} characters</small>
        </label>
      )}
      {content.kind === "file_upload" && (
        <div className="upload-placeholder">
          <strong>File response</strong>
          <p>
            Accepted: {content.allowed_extensions?.join(", ")} · maximum{" "}
            {content.max_files} file(s), {content.max_bytes_per_file} bytes each
          </p>
          <p>Response upload is unavailable in this staff preview.</p>
        </div>
      )}
    </section>
  );
}
export default function CandidatePreview({
  preview,
  base,
  token,
}: {
  preview: Preview;
  base: string;
  token: string;
}) {
  return (
    <article className="candidate" aria-label="Candidate rendering">
      <div className="candidate-top">
        <span className="eyebrow">Candidate view</span>
        <span className="badge">Preview only · answers are not saved</span>
      </div>
      {preview.media?.map((a) => (
        <ProtectedImage key={a.asset_id} asset={a} base={base} token={token} />
      ))}
      <CandidateItem content={preview.content} />
    </article>
  );
}
