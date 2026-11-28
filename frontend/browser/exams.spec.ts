import { expect, test, Page } from "@playwright/test";
const password = process.env.ASSESSMENT_BROWSER_PASSWORD;
const tenant = process.env.ASSESSMENT_BROWSER_TENANT;
const otherTenant = process.env.ASSESSMENT_BROWSER_OTHER_TENANT;
test.beforeAll(() => {
  if (
    process.env.ASSESSMENT_COORDINATOR_BROWSER_GATE !== "1" ||
    !password ||
    !tenant ||
    !otherTenant
  )
    throw new Error(
      "Run scripts/verify_coordinator_browser.py with disposable PostgreSQL.",
    );
});
async function login(page: Page, email = "candidate@example.test") {
  await page.goto("/");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  if (email === "candidate@example.test") {
    await page.getByLabel("Institution", { exact: true }).selectOption(tenant!);
    await page
      .getByRole("button", { name: "Assemble exams", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Assemble an exam" }),
    ).toBeVisible();
  }
}
async function add(page: Page, index = 1) {
  await page
    .getByRole("button", {
      name: `Add version: Assembly question ${index}`,
      exact: true,
    })
    .click();
}
async function validate(page: Page) {
  await page
    .getByRole("button", { name: "Validate blueprint", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Blueprint valid", exact: true }),
  ).toBeVisible();
}
function safe(value: unknown) {
  if (Array.isArray(value)) value.forEach(safe);
  else if (value && typeof value === "object")
    for (const [key, child] of Object.entries(value)) {
      expect([
        "correct_option_id",
        "correct_option_ids",
        "rubric",
        "marker_guidance",
        "accepted_answers",
        "grading",
        "storage",
        "content_hash",
      ]).not.toContain(key);
      safe(child);
    }
}
test("assemble, diagnose duplicates, publish and schedule with committed-response recovery", async ({
  page,
}) => {
  const checks: Promise<void>[] = [],
    requests: string[] = [],
    errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (req) => {
    if (req.url().includes("/api/v1/")) requests.push(req.url());
  });
  page.on("response", (res) => {
    if (
      res.ok() &&
      /question-selections|\/publish|\/publications\//.test(res.url())
    )
      checks.push(res.json().then(safe));
  });
  await login(page);
  await add(page);
  await add(page);
  await page
    .getByRole("button", { name: "Validate blueprint", exact: true })
    .click();
  await expect(
    page.getByText(/same question appears more than once/),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "Remove selection 2 from section 1",
      exact: true,
    })
    .click();
  await add(page, 2);
  await page.getByLabel("Section 1 minimum", { exact: true }).fill("2");
  await page.getByLabel("Section 1 maximum", { exact: true }).fill("2");
  await page
    .getByRole("button", {
      name: "Move selection 2 up in section 1",
      exact: true,
    })
    .click();
  await expect(page.locator(".exam-selected > li").first()).toContainText(
    "Assembly question 2",
  );
  await page
    .getByRole("button", {
      name: "Add coverage rule to section 1",
      exact: true,
    })
    .click();
  await page
    .getByLabel("Section 1 rule 1 taxonomy ID", { exact: true })
    .fill(process.env.ASSESSMENT_BROWSER_TAXONOMY!);
  await page.getByLabel("Section 1 rule 1 minimum", { exact: true }).fill("2");
  await page.getByLabel("Section 1 rule 1 maximum", { exact: true }).fill("2");
  await validate(page);
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByText("Draft revision 1", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Publish saved revision", exact: true }),
  ).toBeDisabled();
  await validate(page);
  let lostPublication = false;
  await page.route("**/publish?expected_revision=*", async (route) => {
    if (!lostPublication) {
      lostPublication = true;
      expect((await route.fetch()).status()).toBe(200);
      await route.abort("connectionfailed");
    } else await route.continue();
  });
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Publish saved revision", exact: true })
    .click();
  await expect(
    page.getByRole("alert", { name: "Exam request error" }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Retry same request", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Frozen publication", exact: true }),
  ).toBeVisible();
  const publishedId = await page
    .getByLabel("Draft or publication ID", { exact: true })
    .inputValue();
  await page.getByText("Assembly question 1", { exact: true }).last().click();
  await expect(
    page.getByRole("article", { name: "Candidate rendering" }),
  ).toBeVisible();
  await page
    .getByLabel("Sitting title", { exact: true })
    .fill("Browser grammar sitting");
  await page.getByLabel("Display timezone", { exact: true }).fill("UTC+05:30");
  const opening = new Date(Date.now() + 3 * 86400000)
    .toISOString()
    .slice(0, 16);
  const closing = new Date(Date.now() + 3 * 86400000 + 2 * 3600000)
    .toISOString()
    .slice(0, 16);
  await page.getByLabel("Opens at", { exact: true }).fill(opening);
  await page.getByLabel("Closes at", { exact: true }).fill(closing);
  let lostSitting = false;
  await page.route("**/exam-sittings/*", async (route) => {
    if (route.request().method() === "PUT" && !lostSitting) {
      lostSitting = true;
      expect((await route.fetch()).status()).toBe(200);
      await route.abort("connectionfailed");
    } else await route.continue();
  });
  await page
    .getByRole("button", { name: "Schedule sitting", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Retry same request", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Retry same request", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Sitting saved", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open sitting", exact: true }).click();
  await expect(
    page.getByText("Browser grammar sitting", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Section 1 maximum", { exact: true }).fill("3");
  let lostRevision = false;
  await page.route("**/drafts/*/revisions", async (route) => {
    if (!lostRevision) {
      lostRevision = true;
      expect((await route.fetch()).status()).toBe(200);
      await route.abort("connectionfailed");
    } else await route.continue();
  });
  await page
    .getByRole("button", { name: "Save new revision", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Retry same request", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Retry same request", exact: true })
    .click();
  await expect(
    page.getByText("Draft revision 2", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Draft or publication ID", { exact: true })
    .fill(publishedId);
  await page
    .getByRole("button", { name: "Open publication", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Published section 1 · 2 selection(s)",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText(`Publication ID: ${publishedId}`, { exact: true }),
  ).toBeVisible();
  await Promise.all(checks);
  expect(requests.some((url) => /\/questions\//.test(url))).toBe(false);
  expect(errors).toEqual([]);
});
test("lost draft save and two-tab stale edit retain form and recover latest revision", async ({
  page,
  context,
}) => {
  await login(page);
  await add(page, 2);
  let lost = false;
  await page.route("**/exam-blueprints/drafts/*", async (route) => {
    if (route.request().method() === "PUT" && !lost) {
      lost = true;
      expect((await route.fetch()).status()).toBe(200);
      await route.abort("connectionfailed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByRole("alert", { name: "Exam request error" }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Retry same request", exact: true })
    .click();
  await expect(
    page.getByText("Draft revision 1", { exact: true }),
  ).toBeVisible();
  const id = await page
    .getByLabel("Draft or publication ID", { exact: true })
    .inputValue();
  const other = await context.newPage();
  await login(other);
  await other.getByLabel("Draft or publication ID", { exact: true }).fill(id);
  await other.getByRole("button", { name: "Open draft", exact: true }).click();
  await expect(
    other.getByText("Draft revision 1", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Section 1 maximum", { exact: true }).fill("2");
  await page
    .getByRole("button", { name: "Save new revision", exact: true })
    .click();
  await expect(
    page.getByText("Draft revision 2", { exact: true }),
  ).toBeVisible();
  await other.getByLabel("Section 1 maximum", { exact: true }).fill("3");
  await other
    .getByRole("button", { name: "Save new revision", exact: true })
    .click();
  await expect(
    other.getByRole("alert", { name: "Exam request error" }),
  ).toBeFocused();
  await expect(
    other.getByLabel("Section 1 maximum", { exact: true }),
  ).toHaveValue("3");
  other.once("dialog", (dialog) => dialog.accept());
  await other
    .getByRole("button", { name: "Reload latest revision", exact: true })
    .click();
  await expect(
    other.getByText("Draft revision 2", { exact: true }),
  ).toBeVisible();
  await expect(
    other.getByLabel("Section 1 maximum", { exact: true }),
  ).toHaveValue("2");
  await other.close();
});
test("narrow keyboard assembly, empty institution and reviewer role boundary", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await expect(
    page.getByRole("button", { name: "Validate blueprint", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Validate blueprint", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText(/Selected question count is outside/),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page
    .getByLabel("Institution", { exact: true })
    .selectOption(otherTenant!);
  await page
    .getByRole("button", { name: "Assemble exams", exact: true })
    .click();
  await expect(
    page.getByText("No approved versions on this page."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Add version:/ })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await login(page, "outsider@example.test");
  await expect(
    page.getByRole("button", { name: "Assemble exams", exact: true }),
  ).toHaveCount(0);
});
