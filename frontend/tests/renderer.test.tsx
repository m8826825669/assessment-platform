import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { CandidateItem } from "../components/candidate-preview";
import { ContentEditor } from "../components/content-editor";
import { kinds, newContent, PublicContent } from "../lib/types";
import examples from "../../docs/QUESTION_CONTENT_EXAMPLES.json";

describe("candidate renderer boundary", () => {
  for (const example of examples)
    it(`escapes and excludes ${example.kind} marking fields`, () => {
      // Deliberately pass a private object: renderer must only read public fields.
      const content = {
        ...example,
        prompt: '<img src=x onerror="secret()">',
        marker_guidance: "PRIVATE_GUIDANCE_SENTINEL",
        expected: "PRIVATE_NUMBER_SENTINEL",
        correct_option_id: "PRIVATE_OPTION_SENTINEL",
        accepted_answers: ["PRIVATE_ANSWER_SENTINEL"],
        rubric: [{ description: "PRIVATE_RUBRIC_SENTINEL" }],
        children:
          example.kind === "passage_group"
            ? [
                {
                  kind: "essay",
                  item_id: "child",
                  prompt: "Child",
                  points: "1",
                  marker_guidance: "NESTED_PRIVATE_SENTINEL",
                },
              ]
            : undefined,
      } as unknown as PublicContent;
      const html = renderToStaticMarkup(<CandidateItem content={content} />);
      expect(html).toContain("&lt;img");
      expect(html).not.toContain('<img src="x"');
      expect(html).not.toMatch(/PRIVATE_.*SENTINEL/);
      expect(html).not.toContain("correct_option_id");
    });
});
describe("seven typed editors", () => {
  for (const kind of kinds)
    it(`provides labeled ${kind} fields`, () => {
      const html = renderToStaticMarkup(
        <ContentEditor value={newContent(kind)} onChange={() => {}} />,
      );
      expect(html).toContain("Candidate prompt");
      expect(html).toContain("Item identifier");
      expect(html).toContain("Points");
      if (["essay", "file_upload"].includes(kind))
        expect(html).toContain("Staff only · Marking rubric");
    });
});

describe("saved prompt labels", () => {
  it("keeps parent and passage-child labels independent of populated values", () => {
    const saved = examples.find((example) => example.kind === "passage_group")!;
    const html = renderToStaticMarkup(
      <ContentEditor
        value={saved as unknown as import("../lib/types").Content}
        onChange={() => {}}
      />,
    );
    const ids = Array.from(
      html.matchAll(/<label for="([^"]+)">Candidate prompt<\/label>/g),
      (match) => match[1],
    );
    expect(ids).toHaveLength(1 + saved.children!.length);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(html).toContain(`<textarea id="${id}"`);
    }
  });
});
