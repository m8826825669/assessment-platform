import { expect, test, Page } from "@playwright/test";
import examples from "../../docs/QUESTION_IMPORT_EXAMPLE.json";
const password = process.env.ASSESSMENT_BROWSER_PASSWORD;
test.beforeAll(() => {
  if (process.env.ASSESSMENT_BROWSER_GATE !== "1" || !password)
    throw new Error(
      "Run scripts/verify_browser.py; this gate requires disposable real services.",
    );
});
async function login(page: Page, email: string) {
  await page.goto("/");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}
async function logout(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
}
const forbidden = [
  "correct_option_id",
  "correct_option_ids",
  "expected",
  "absolute_tolerance",
  "accepted_answers",
  "normalization",
  "marker_guidance",
  "rubric",
  "content_hash",
  "scoring",
];
function safe(value: unknown) {
  if (Array.isArray(value)) value.forEach(safe);
  else if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      expect(forbidden).not.toContain(key);
      safe(child);
    }
  }
}
test("all seven types: import, author, review, coordinator, immutable old snapshot", async ({
  page,
}) => {
  const failures: string[] = [];
  page.on("pageerror", (e) => failures.push(e.message));
  const previews: unknown[] = [];
  const pending: Promise<void>[] = [];
  page.on("response", (response) => {
    if (
      (response.url().includes("/preview") ||
        response.url().includes("/question-selections")) &&
      response.ok()
    )
      pending.push(
        response.json().then((body) => {
          safe(body);
          previews.push(body);
        }),
      );
  });
  await login(page, "browser_author@example.test");
  await page
    .getByRole("button", { name: "Import questions", exact: true })
    .click();
  await page
    .getByLabel("Staff only · Import JSON")
    .fill(JSON.stringify(examples));
  await page
    .getByRole("button", { name: "Validate preview", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "7 valid draft(s)" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Generate retry key" }).click();
  await page.getByRole("button", { name: "Commit draft batch" }).click();
  await expect(
    page.getByRole("heading", { name: "Batch acknowledged · 7 draft(s)" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry same import" }).click();
  await expect(
    page.getByRole("heading", { name: "Batch acknowledged · 7 draft(s)" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Question bank", exact: true })
    .click();
  for (const item of examples.items) {
    const row = page.getByRole("row").filter({ hasText: item.title });
    await row.getByRole("button", { name: /Open/ }).click();
    const prompt = page.getByLabel("Candidate prompt", { exact: true }).first();
    await expect(prompt).toHaveValue(item.content.prompt);
    await prompt.fill(item.content.prompt + " Browser reviewed.");
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await expect(page.getByRole("status")).toContainText(
      "Saved immutable version 2",
    );
    await page.getByRole("button", { name: "Preview saved version" }).click();
    await expect(
      page.getByRole("article", { name: "Candidate rendering" }),
    ).toBeVisible();
    await expect(
      page.getByRole("article", { name: "Candidate rendering" }),
    ).not.toContainText("Private reference explanation");
    await page.getByRole("button", { name: "Submit for review" }).click();
    await expect(page.getByRole("status")).toContainText("submitted");
  }
  await logout(page);
  await login(page, "outsider@example.test");
  for (const item of examples.items) {
    const row = page.getByRole("row").filter({ hasText: item.title });
    await row.getByRole("button", { name: /Review/ }).click();
    await page.getByRole("button", { name: "Preview saved version" }).click();
    await expect(
      page.getByRole("article", { name: "Candidate rendering" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Approve exact version" }).click();
    await expect(page.getByRole("status")).toContainText("approved");
  }
  await logout(page);
  await login(page, "candidate@example.test"); // fixture role is coordinator
  for (const item of examples.items) {
    await page
      .getByRole("row")
      .filter({ hasText: item.title })
      .getByRole("button", { name: /Preview/ })
      .click();
    await expect(
      page.getByRole("article", { name: "Candidate rendering" }),
    ).toBeVisible();
  }
  const old = await page
    .getByRole("article", { name: "Candidate rendering" })
    .innerText();
  await logout(page);
  await login(page, "browser_author@example.test");
  await page
    .getByRole("row")
    .filter({ hasText: examples.items[6].title })
    .getByRole("button", { name: /Open/ })
    .click();
  await page.getByLabel("Question title").fill("Changed newer draft");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("version 3");
  await logout(page);
  await login(page, "candidate@example.test");
  await page
    .getByRole("row")
    .filter({ hasText: examples.items[6].title })
    .getByRole("button", { name: /Preview/ })
    .click();
  expect(
    await page
      .getByRole("article", { name: "Candidate rendering" })
      .innerText(),
  ).toBe(old);
  await Promise.all(pending);
  expect(previews.length).toBeGreaterThanOrEqual(14);
  expect(failures).toEqual([]);
});
test("real scanned image, narrow layout, keyboard and stale edit recovery", async ({
  page,
  browser,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "browser_author@example.test");
  await page.getByRole("button", { name: "New question" }).click();
  await page.getByLabel("Question title").fill("Accessible image journey");
  await page
    .getByLabel("Candidate prompt", { exact: true })
    .fill("Choose a shape.");
  await page.getByLabel("Option 1 text").fill("Rectangle");
  await page.getByLabel("Option 2 text").fill("Circle");
  await page
    .getByLabel("Accessible image description")
    .fill("A small green rectangle with four corners");
  // Valid deterministic PNG, generated by the Python fixture and passed only as synthetic bytes.
  const png = Buffer.from(process.env.ASSESSMENT_BROWSER_PNG!, "base64");
  await page.getByLabel("Image file", { exact: true }).setInputFiles({
    name: "rectangle.png",
    mimeType: "image/png",
    buffer: png,
  });
  await page.getByRole("button", { name: "1. Reserve image" }).click();
  await page.getByRole("button", { name: "2. Upload bytes" }).click();
  await page.getByRole("button", { name: "3. Scan / retry scan" }).click();
  await page.getByRole("button", { name: "4. Attach clean image" }).click();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("version 1");
  await page.getByRole("button", { name: "Preview saved version" }).click();
  await expect(
    page.getByRole("img", {
      name: "A small green rectangle with four corners",
    }),
  ).toBeVisible();
  const second = await browser.newPage();
  await login(second, "browser_author@example.test");
  await second
    .getByRole("row")
    .filter({ hasText: "Accessible image journey" })
    .getByRole("button", { name: /Open/ })
    .click();
  await second.getByLabel("Question title").fill("Saved from second tab");
  await second.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(second.getByRole("status")).toContainText("version 2");
  await page.getByLabel("Question title").fill("Retain my unsaved title");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByRole("alert", { name: "Workspace error" }),
  ).toContainText("record changed");
  await expect(page.getByLabel("Question title")).toHaveValue(
    "Retain my unsaved title",
  );
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toBeVisible();
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Reload current version" }).click();
  await expect(page.getByLabel("Question title")).toHaveValue(
    "Saved from second tab",
  );
  await second.close();
  await expect(
    page.getByRole("button", { name: "Reload current version" }),
  ).toBeEnabled();
  const layout = await page.evaluate(() => {
    function elements(root: Document | ShadowRoot): HTMLElement[] {
      return Array.from(root.querySelectorAll<HTMLElement>("*")).flatMap(
        (element) => [
          element,
          ...(element.shadowRoot ? elements(element.shadowRoot) : []),
        ],
      );
    }
    return {
      viewport: window.innerWidth,
      document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
      overflowing: elements(document)
        .filter(
          (element) =>
            !element.closest(".table-scroll") ||
            ["absolute", "fixed"].includes(getComputedStyle(element).position),
        )
        .map((element) => {
          const box = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return {
            tag: element.tagName,
            className: String(element.className),
            left: Math.round(box.left),
            right: Math.round(box.right),
            width: Math.round(box.width),
            scrollWidth: element.scrollWidth,
            clientWidth: element.clientWidth,
            overflowX: style.overflowX,
            position: style.position,
            containingBlock: element.offsetParent?.tagName ?? null,
            inShadow: element.getRootNode() instanceof ShadowRoot,
          };
        })
        .filter(
          (box) =>
            box.width > 0 && (box.right > window.innerWidth || box.left < 0),
        )
        .slice(0, 30),
    };
  });
  await test.info().attach("narrow-layout.json", {
    body: JSON.stringify(layout, null, 2),
    contentType: "application/json",
  });
  expect(layout.document, JSON.stringify(layout)).toBeLessThanOrEqual(
    layout.viewport,
  );
});
test("tenant and role boundaries remain visible in the browser", async ({
  page,
}) => {
  await login(page, "admin_b@example.test");
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "Synthetic single_choice question" }),
  ).toHaveCount(0);
  await logout(page);
  await login(page, "candidate@example.test");
  await expect(page.getByRole("button", { name: "New question" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Import questions", exact: true }),
  ).toHaveCount(0);
  await logout(page);
  await login(page, "browser_author@example.test");
  await page
    .getByRole("button", { name: "Import questions", exact: true })
    .click();
  await page
    .getByLabel("Staff only · Import JSON")
    .fill('{"schema_version":"assessment-question-import.v1","items":[]}');
  await page
    .getByRole("button", { name: "Validate preview", exact: true })
    .click();
  await expect(
    page.getByRole("alert", { name: "Workspace error" }),
  ).toBeVisible();
  await expect(page.getByLabel("Staff only · Import JSON")).not.toBeEmpty();
  await expect(
    page.getByRole("button", { name: "Commit draft batch" }),
  ).toHaveCount(0);
});
