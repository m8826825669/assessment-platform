import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PublicationSummary } from "../components/exam-workspace";
import {
  Publication,
  diagnosticText,
  requireId,
  scheduleInstant,
} from "../lib/exams";
it.each([
  ["2026-11-28T15:30", "UTC+05:30", "2026-11-28T10:00:00.000Z"],
  ["2026-11-28T01:30", "UTC-04:00", "2026-11-28T05:30:00.000Z"],
  ["2026-11-28T01:30", "UTC", "2026-11-28T01:30:00.000Z"],
  ["2026-11-28T01:30", "UTC+14:00", "2026-11-27T11:30:00.000Z"],
])(
  "converts explicit fixed offset %s %s without browser timezone",
  (value, zone, expected) =>
    expect(scheduleInstant(value, zone)).toBe(expected),
);
it.each([
  ["", "UTC"],
  ["2026-02-30T00:00", "UTC"],
  ["2026-11-28T10:00", "Asia/Kolkata"],
  ["2026-11-28T10:00", "UTC+14:30"],
  ["2026-11-28T10:00", "UTC+02:60"],
  ["2026-11-28T10:00", "UTC-15:00"],
])("rejects invalid calendar/offset %s %s", (value, zone) =>
  expect(() => scheduleInstant(value, zone)).toThrow(),
);
it("requires a bounded UUID for recovery", () => {
  expect(() => requireId("../../private")).toThrow();
  expect(requireId("524723e5-9b05-4387-9fe1-f511861dd953")).toBe(
    "524723e5-9b05-4387-9fe1-f511861dd953",
  );
});
it("explains diagnostic location and counts", () => {
  expect(
    diagnosticText({
      code: "coverage_count",
      section_index: 1,
      rule_index: 0,
      minimum: 2,
      maximum: 3,
      observed: 1,
    }),
  ).toContain("Section 2, coverage rule 1");
  expect(
    diagnosticText({
      code: "section_count",
      section_index: 0,
      minimum: 1,
      maximum: 1,
      observed: 0,
    }),
  ).toContain("Observed 0; required 1–1");
});
it("renders frozen public content explicitly without injected keys or storage", () => {
  const publication = {
    id: "frozen",
    schema_version: 1,
    policy: {
      duration_minutes: 30,
      negative_marks: "0",
      unanswered_points: "0",
      item_weight: "1",
      percentage_decimal_places: 2,
      percentage_rounding: "half_up",
      invalid_items: "exclude",
      zero_available_points: "no_percentage",
      secret: "PRIVATE_POLICY",
    },
    grading: "PRIVATE_GRADING",
    sections: [
      {
        minimum: 1,
        maximum: 1,
        coverage: [],
        items: [
          {
            version_id: "v1",
            question_id: "q1",
            title: "<script>Exam</script>",
            content: {
              kind: "single_choice",
              item_id: "x",
              prompt: "Safe prompt",
              points: "1",
              options: [{ id: "a", text: "Yes" }],
              correct_option_id: "PRIVATE_KEY",
            },
            media: [],
            taxonomy: [],
            storage: "PRIVATE_STORAGE",
          },
        ],
      },
    ],
  } as unknown as Publication;
  const html = renderToStaticMarkup(
    <PublicationSummary
      publication={publication}
      base="tenants/t"
      token="not-a-session"
    />,
  );
  expect(html).toContain("Safe prompt");
  expect(html).toContain("30 minutes");
  expect(html).toContain("&lt;script&gt;");
  expect(html).not.toContain("PRIVATE_");
  expect(html).not.toContain("<script>");
});
