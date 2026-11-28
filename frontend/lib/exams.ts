import { PublicContent, Media, Term } from "./types";
export type Section = {
  version_ids: string[];
  minimum: number;
  maximum: number;
  coverage: { term_id: string; minimum: number; maximum: number }[];
};
export type Blueprint = { sections: Section[] };
export type Draft = Blueprint & {
  id: string;
  exam_id: string;
  revision: number;
  parent_id: string | null;
};
export type Diagnostic = {
  code: string;
  section_index: number;
  rule_index?: number | null;
  selection_index?: number | null;
  minimum?: number | null;
  maximum?: number | null;
  observed?: number | null;
};
export type Validation = { valid: boolean; diagnostics: Diagnostic[] };
export type Publication = {
  id: string;
  schema_version: number;
  policy: {
    duration_minutes: number;
    negative_marks: string;
    unanswered_points: string;
    item_weight: string;
    percentage_decimal_places: number;
    percentage_rounding: string;
    invalid_items: string;
    zero_available_points: string;
  };
  sections: {
    minimum: number;
    maximum: number;
    coverage: Section["coverage"];
    items: {
      version_id: string;
      question_id: string;
      title: string;
      content: PublicContent;
      media: Media[];
      taxonomy: Term[];
    }[];
  }[];
};
export type Sitting = {
  id: string;
  publication_id: string;
  title: string;
  opens_at: string;
  closes_at: string;
  display_timezone: string;
  duration_minutes: number;
};
export type Operation = {
  kind: "draft" | "publication" | "sitting";
  identity: string;
  path: string;
  method: string;
  body?: string;
};
export const emptyBlueprint = (): Blueprint => ({
  sections: [{ version_ids: [], minimum: 1, maximum: 1, coverage: [] }],
});
export function requireId(id: string) {
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
  )
    throw new Error("Enter a complete UUID reference.");
  return id;
}
export function scheduleInstant(value: string, zone: string) {
  const match = /^UTC([+-])(\d{2}):(\d{2})$/.exec(zone);
  if (
    zone !== "UTC" &&
    (!match ||
      Number(match[2]) > 14 ||
      Number(match[3]) > 59 ||
      (Number(match[2]) === 14 && Number(match[3]) !== 0))
  )
    throw new Error(
      "Use UTC or a fixed offset up to UTC±14:00, such as UTC+05:30.",
    );
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value))
    throw new Error("Enter an opening and closing date and time.");
  const minutes = match
    ? (Number(match[2]) * 60 + Number(match[3])) * (match[1] === "+" ? 1 : -1)
    : 0;
  const local = new Date(value + ":00Z");
  if (
    !Number.isFinite(local.getTime()) ||
    local.toISOString().slice(0, 16) !== value
  )
    throw new Error("Enter a valid calendar date and time.");
  return new Date(local.getTime() - minutes * 60000).toISOString();
}
export function diagnosticText(item: Diagnostic) {
  const messages: Record<string, string> = {
    sections_required: "Add at least one section.",
    invalid_section_bounds: "Minimum must not exceed maximum.",
    invalid_coverage_bounds: "Coverage minimum must not exceed maximum.",
    section_count: "Selected question count is outside the section bounds.",
    selection_unavailable:
      "A selected version is unavailable. Remove it and choose an approved version.",
    duplicate_question:
      "The same question appears more than once. Keep one exact version.",
    coverage_count:
      "Selected versions do not meet the saved taxonomy coverage bounds.",
  };
  return `Section ${item.section_index + 1}${item.rule_index != null ? `, coverage rule ${item.rule_index + 1}` : ""}: ${messages[item.code] ?? "Review this section."}${item.observed != null ? ` Observed ${item.observed}; required ${item.minimum}–${item.maximum}.` : ""}`;
}
