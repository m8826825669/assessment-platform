"use client";
import { useId } from "react";
import { Content, Kind, kinds, label, newContent } from "../lib/types";
export function ContentEditor({
  value,
  onChange,
  nested = false,
}: {
  value: Content;
  onChange: (content: Content) => void;
  nested?: boolean;
}) {
  const promptId = useId();
  const set = (patch: Partial<Content>) => onChange({ ...value, ...patch });
  return (
    <fieldset className="content-fields">
      <legend>{nested ? "Passage child" : "Question content"}</legend>
      <div className="form-grid">
        <label>
          Question type
          <select
            value={value.kind}
            onChange={(e) =>
              onChange(newContent(e.target.value as Kind, value.item_id))
            }
          >
            {kinds
              .filter((k) => !nested || k !== "passage_group")
              .map((k) => (
                <option key={k} value={k}>
                  {label(k)}
                </option>
              ))}
          </select>
        </label>
        <label>
          Item identifier
          <input
            required
            pattern="[a-z][a-z0-9_-]{0,63}"
            value={value.item_id}
            onChange={(e) => set({ item_id: e.target.value })}
          />
        </label>
        <label>
          Points
          <input
            required
            inputMode="decimal"
            value={value.points}
            onChange={(e) => set({ points: e.target.value })}
          />
        </label>
      </div>
      <div className="prompt-field">
        <label htmlFor={promptId}>Candidate prompt</label>
        <textarea
          id={promptId}
          required
          maxLength={16000}
          value={value.prompt}
          onChange={(e) => set({ prompt: e.target.value })}
        />
      </div>
      {value.options && (
        <fieldset>
          <legend>Answer options</legend>
          {value.options.map((option, i) => (
            <div className="option-row" key={i}>
              <label>
                Option {i + 1} identifier
                <input
                  required
                  value={option.id}
                  onChange={(e) =>
                    set({
                      options: value.options!.map((o, n) =>
                        n === i ? { ...o, id: e.target.value } : o,
                      ),
                    })
                  }
                />
              </label>
              <label>
                Option {i + 1} text
                <input
                  required
                  maxLength={1000}
                  value={option.text}
                  onChange={(e) =>
                    set({
                      options: value.options!.map((o, n) =>
                        n === i ? { ...o, text: e.target.value } : o,
                      ),
                    })
                  }
                />
              </label>
              <button
                type="button"
                className="quiet"
                disabled={value.options!.length <= 2}
                onClick={() =>
                  set({ options: value.options!.filter((_, n) => n !== i) })
                }
              >
                Remove option {i + 1}
              </button>
            </div>
          ))}
          <button
            type="button"
            className="secondary"
            disabled={value.options.length >= 20}
            onClick={() =>
              set({
                options: [
                  ...value.options!,
                  { id: `option_${value.options!.length + 1}`, text: "" },
                ],
              })
            }
          >
            Add option
          </button>
        </fieldset>
      )}
      {value.kind === "single_choice" && (
        <div className="private">
          <label>
            Staff only · Correct option
            <select
              value={value.correct_option_id}
              onChange={(e) => set({ correct_option_id: e.target.value })}
            >
              {value.options!.map((o, i) => (
                <option value={o.id} key={i}>
                  {o.id}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {value.kind === "multiple_select" && (
        <fieldset className="private">
          <legend>Staff only · Correct options (all or nothing)</legend>
          {value.options!.map((o, i) => (
            <label className="check" key={i}>
              <input
                type="checkbox"
                checked={value.correct_option_ids!.includes(o.id)}
                onChange={(e) =>
                  set({
                    correct_option_ids: e.target.checked
                      ? [...value.correct_option_ids!, o.id]
                      : value.correct_option_ids!.filter((id) => id !== o.id),
                  })
                }
              />
              {o.id}
            </label>
          ))}
        </fieldset>
      )}
      {value.kind === "numeric" && (
        <>
          <div className="private form-grid">
            <label>
              Staff only · Expected number
              <input
                required
                inputMode="decimal"
                value={value.expected}
                onChange={(e) => set({ expected: e.target.value })}
              />
            </label>
            <label>
              Staff only · Absolute tolerance
              <input
                required
                inputMode="decimal"
                value={value.absolute_tolerance}
                onChange={(e) => set({ absolute_tolerance: e.target.value })}
              />
            </label>
          </div>
          <label>
            Unit label (optional)
            <input
              maxLength={1000}
              value={value.unit_label ?? ""}
              onChange={(e) => set({ unit_label: e.target.value || null })}
            />
          </label>
        </>
      )}
      {value.kind === "short_answer" && (
        <div className="private">
          <label>
            Staff only · Accepted answers (one per line)
            <textarea
              required
              value={value.accepted_answers!.join("\n")}
              onChange={(e) =>
                set({ accepted_answers: e.target.value.split("\n") })
              }
            />
          </label>
          <p>Unicode NFKC normalization</p>
          <label className="check">
            <input
              type="checkbox"
              checked={value.normalization?.case_sensitive ?? false}
              onChange={(e) =>
                set({
                  normalization: {
                    unicode_form: "NFKC",
                    collapse_whitespace:
                      value.normalization?.collapse_whitespace ?? true,
                    case_sensitive: e.target.checked,
                  },
                })
              }
            />
            Case sensitive
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={value.normalization?.collapse_whitespace ?? true}
              onChange={(e) =>
                set({
                  normalization: {
                    unicode_form: "NFKC",
                    case_sensitive:
                      value.normalization?.case_sensitive ?? false,
                    collapse_whitespace: e.target.checked,
                  },
                })
              }
            />
            Collapse whitespace
          </label>
        </div>
      )}
      {value.rubric && (
        <fieldset className="private">
          <legend>Staff only · Marking rubric</legend>
          {value.rubric.map((r, i) => (
            <div className="rubric-row" key={i}>
              <label>
                Criterion {i + 1} identifier
                <input
                  required
                  value={r.id}
                  onChange={(e) =>
                    set({
                      rubric: value.rubric!.map((x, n) =>
                        n === i ? { ...x, id: e.target.value } : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                Criterion {i + 1} description
                <textarea
                  required
                  value={r.description}
                  onChange={(e) =>
                    set({
                      rubric: value.rubric!.map((x, n) =>
                        n === i ? { ...x, description: e.target.value } : x,
                      ),
                    })
                  }
                />
              </label>
              <label>
                Criterion {i + 1} points
                <input
                  required
                  inputMode="decimal"
                  value={r.max_points}
                  onChange={(e) =>
                    set({
                      rubric: value.rubric!.map((x, n) =>
                        n === i ? { ...x, max_points: e.target.value } : x,
                      ),
                    })
                  }
                />
              </label>
              <button
                type="button"
                className="quiet"
                disabled={value.rubric!.length <= 1}
                onClick={() =>
                  set({ rubric: value.rubric!.filter((_, n) => n !== i) })
                }
              >
                Remove criterion {i + 1}
              </button>
            </div>
          ))}
          <button
            type="button"
            className="secondary"
            disabled={value.rubric.length >= 30}
            onClick={() =>
              set({
                rubric: [
                  ...value.rubric!,
                  {
                    id: `criterion_${value.rubric!.length + 1}`,
                    description: "",
                    max_points: "1",
                  },
                ],
              })
            }
          >
            Add criterion
          </button>
          <p>Criterion points must total the question points.</p>
          <label>
            Staff only · Marker guidance
            <textarea
              required
              maxLength={16000}
              value={value.marker_guidance}
              onChange={(e) => set({ marker_guidance: e.target.value })}
            />
          </label>
        </fieldset>
      )}
      {(value.kind === "essay" || value.kind === "short_answer") && (
        <label>
          Maximum response characters
          <input
            type="number"
            min="1"
            max={value.kind === "essay" ? 100000 : 4000}
            required
            value={value.max_response_characters}
            onChange={(e) =>
              set({ max_response_characters: Number(e.target.value) })
            }
          />
        </label>
      )}
      {value.kind === "file_upload" && (
        <fieldset>
          <legend>Candidate upload policy</legend>
          <div className="inline">
            {[".pdf", ".txt", ".png", ".jpg", ".jpeg"].map((ext) => (
              <label className="check" key={ext}>
                <input
                  type="checkbox"
                  checked={value.allowed_extensions!.includes(ext)}
                  onChange={(e) =>
                    set({
                      allowed_extensions: e.target.checked
                        ? [...value.allowed_extensions!, ext]
                        : value.allowed_extensions!.filter((x) => x !== ext),
                    })
                  }
                />
                {ext}
              </label>
            ))}
          </div>
          <div className="form-grid">
            <label>
              Maximum files
              <input
                type="number"
                required
                min="1"
                max="5"
                value={value.max_files}
                onChange={(e) => set({ max_files: Number(e.target.value) })}
              />
            </label>
            <label>
              Bytes per file
              <input
                type="number"
                required
                min="1"
                max="20971520"
                value={value.max_bytes_per_file}
                onChange={(e) =>
                  set({ max_bytes_per_file: Number(e.target.value) })
                }
              />
            </label>
          </div>
          <p>
            This defines the question policy. Candidate response uploads arrive
            in P4.
          </p>
        </fieldset>
      )}
      {value.kind === "passage_group" && (
        <>
          <label>
            Passage
            <textarea
              required
              maxLength={16000}
              value={value.passage}
              onChange={(e) => set({ passage: e.target.value })}
            />
          </label>
          {value.children!.map((child, i) => (
            <div className="child" key={i}>
              <ContentEditor
                nested
                value={child}
                onChange={(content) =>
                  set({
                    children: value.children!.map((c, n) =>
                      n === i ? content : c,
                    ),
                  })
                }
              />
              <button
                type="button"
                className="quiet"
                disabled={value.children!.length <= 1}
                onClick={() =>
                  set({ children: value.children!.filter((_, n) => n !== i) })
                }
              >
                Remove child {i + 1}
              </button>
            </div>
          ))}
          <button
            type="button"
            className="secondary"
            disabled={value.children!.length >= 20}
            onClick={() =>
              set({
                children: [
                  ...value.children!,
                  newContent(
                    "single_choice",
                    `child_${value.children!.length + 1}`,
                  ),
                ],
              })
            }
          >
            Add passage child
          </button>
          <p>
            Child points must total the group points. Child identifiers must be
            distinct.
          </p>
        </>
      )}
    </fieldset>
  );
}
