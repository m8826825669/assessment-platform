export const kinds = [
  "single_choice",
  "multiple_select",
  "numeric",
  "short_answer",
  "essay",
  "file_upload",
  "passage_group",
] as const;
export type Kind = (typeof kinds)[number];
export type Option = { id: string; text: string };
export type Criterion = { id: string; description: string; max_points: string };
export type Content = {
  kind: Kind;
  item_id: string;
  prompt: string;
  points: string;
  options?: Option[];
  correct_option_id?: string;
  correct_option_ids?: string[];
  scoring?: string;
  expected?: string;
  absolute_tolerance?: string;
  unit_label?: string | null;
  accepted_answers?: string[];
  normalization?: {
    unicode_form: "NFKC";
    case_sensitive: boolean;
    collapse_whitespace: boolean;
  };
  max_response_characters?: number;
  rubric?: Criterion[];
  marker_guidance?: string;
  allowed_extensions?: string[];
  max_files?: number;
  max_bytes_per_file?: number;
  passage?: string;
  children?: Content[];
};
export type PublicContent = Pick<
  Content,
  | "kind"
  | "item_id"
  | "prompt"
  | "points"
  | "options"
  | "unit_label"
  | "max_response_characters"
  | "allowed_extensions"
  | "max_files"
  | "max_bytes_per_file"
  | "passage"
> & { children?: PublicContent[] };
export type Media = {
  asset_id: string;
  mime_type: string;
  description: string;
  width: number | null;
  height: number | null;
  state?: string;
  revision?: number;
  error_code?: string | null;
};
export type Term = {
  id: string;
  kind: string;
  code: string;
  label: string;
  parent_id: string | null;
  revision: number;
  state?: string;
};
export type Row = {
  question_id: string;
  version_id: string;
  version_number?: number;
  title: string;
  state?: string;
  review_revision?: number;
  taxonomy: Term[];
  media: Media[];
  content?: PublicContent;
};
export type Detail = Omit<Row, "content"> & {
  tenant_id: string;
  created_by: string;
  revision: number;
  content_hash: string;
  authored_by: string;
  content: Content;
  decisions?: {
    id: string;
    sequence: number;
    action: string;
    state: string;
    reason: string | null;
    created_at: string;
  }[];
};
export type Preview = {
  question_id?: string;
  version_id?: string;
  content: PublicContent;
  media?: Media[];
};
export type Receipt = {
  batch_id: string;
  item_count: number;
  created_as: string;
  items: { reference: string; question_id: string; version_id: string }[];
};
export type Access = { role: string; permissions: string[]; tenant_id: string };
export type Institution = {
  tenant_id: string;
  institution_name: string;
  role: string;
};
export function label(value: string) {
  return value.replaceAll("_", " ");
}
export function newContent(kind: Kind, id = "item_one"): Content {
  const base = { kind, item_id: id, prompt: "", points: "1" };
  if (kind === "single_choice")
    return {
      ...base,
      options: [
        { id: "a", text: "" },
        { id: "b", text: "" },
      ],
      correct_option_id: "a",
    };
  if (kind === "multiple_select")
    return {
      ...base,
      options: [
        { id: "a", text: "" },
        { id: "b", text: "" },
      ],
      correct_option_ids: ["a"],
      scoring: "all_or_nothing",
    };
  if (kind === "numeric")
    return {
      ...base,
      expected: "0",
      absolute_tolerance: "0",
      unit_label: null,
    };
  if (kind === "short_answer")
    return {
      ...base,
      accepted_answers: [""],
      normalization: {
        unicode_form: "NFKC",
        case_sensitive: false,
        collapse_whitespace: true,
      },
      max_response_characters: 1000,
    };
  if (kind === "passage_group")
    return {
      ...base,
      passage: "",
      children: [newContent("single_choice", "child_one")],
    };
  const manual = {
    ...base,
    rubric: [{ id: "criterion_one", description: "", max_points: "1" }],
    marker_guidance: "",
  };
  return kind === "essay"
    ? { ...manual, max_response_characters: 20000 }
    : {
        ...manual,
        allowed_extensions: [".pdf"],
        max_files: 1,
        max_bytes_per_file: 10485760,
      };
}
