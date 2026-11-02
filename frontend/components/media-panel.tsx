"use client";
import { useState } from "react";
import { request } from "../lib/api";
import { Media } from "../lib/types";
export default function MediaPanel({
  base,
  token,
  run,
  onAttach,
}: {
  base: string;
  token: string;
  run: (job: () => Promise<void>) => void;
  onAttach: (asset: Media) => void;
}) {
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [asset, setAsset] = useState<Media | null>(null);
  const [lookup, setLookup] = useState("");
  const [busy, setBusy] = useState(false);
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
      <h3>Protected image</h3>
      <p>
        PNG or JPEG · up to 8 MiB. Reserve, upload, scan, then attach.
        Descriptions are immutable.
      </p>
      <label>
        Accessible image description
        <textarea
          maxLength={1000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>
      <label>
        Image file
        <input
          type="file"
          accept="image/png,image/jpeg"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <button
        type="button"
        className="secondary"
        disabled={busy || !!asset || !file || description.trim().length < 3}
        onClick={() =>
          act(async () => {
            if (
              !file ||
              file.size > 8 * 1024 * 1024 ||
              !["image/png", "image/jpeg"].includes(file.type)
            )
              throw new Error("Choose a PNG/JPEG no larger than 8 MiB.");
            const reserved = await request<Media>(`${base}/media`, token, {
              method: "POST",
              body: JSON.stringify({
                filename: file.name,
                mime_type: file.type,
                description,
              }),
            });
            setAsset(reserved);
            setLookup(reserved.asset_id);
          })
        }
      >
        1. Reserve image
      </button>
      {asset && (
        <div className="notice">
          <p>
            <strong>{asset.state ?? "Existing image"}</strong> · revision{" "}
            {asset.revision}
          </p>
          <label>
            Asset ID
            <input readOnly value={asset.asset_id} />
          </label>
          <p>{asset.description}</p>
          <div className="inline">
            <button
              type="button"
              className="secondary"
              disabled={busy || !file || asset.state !== "pending"}
              onClick={() =>
                act(async () =>
                  setAsset(
                    await request<Media>(
                      `${base}/media/${asset.asset_id}/content?expected_revision=${asset.revision}`,
                      token,
                      {
                        method: "PUT",
                        headers: { "Content-Type": file!.type },
                        body: file!,
                      },
                    ),
                  ),
                )
              }
            >
              2. Upload bytes
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy || asset.state !== "quarantine"}
              onClick={() =>
                act(async () =>
                  setAsset(
                    await request<Media>(
                      `${base}/media/${asset.asset_id}/scan`,
                      token,
                      {
                        method: "POST",
                        body: JSON.stringify({
                          expected_revision: asset.revision,
                        }),
                      },
                    ),
                  ),
                )
              }
            >
              3. Scan / retry scan
            </button>
            <button
              type="button"
              disabled={busy || asset.state !== "clean"}
              onClick={() => onAttach(asset)}
            >
              4. Attach clean image
            </button>
          </div>
          <p>
            {asset.state === "quarantine"
              ? "Keep this ID. A scan error leaves bytes quarantined; retry after services recover."
              : asset.state === "rejected"
                ? "Rejected bytes cannot be attached. Start a new image reservation."
                : "Only clean media can be attached."}
          </p>
        </div>
      )}
      <label>
        Recover or reuse an image by asset ID
        <input value={lookup} onChange={(e) => setLookup(e.target.value)} />
      </label>
      <div className="inline">
        <button
          type="button"
          className="secondary"
          disabled={busy || !lookup}
          onClick={() =>
            act(async () =>
              setAsset(await request<Media>(`${base}/media/${lookup}`, token)),
            )
          }
        >
          Load image status
        </button>
        <button
          type="button"
          className="quiet"
          onClick={() => {
            setAsset(null);
            setFile(null);
          }}
        >
          Start another image
        </button>
      </div>
    </section>
  );
}
