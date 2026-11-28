import { expect, test, Page } from "@playwright/test";
const password = process.env.ASSESSMENT_BROWSER_PASSWORD;
const candidate = process.env.ASSESSMENT_BROWSER_CANDIDATE;
const tenant = process.env.ASSESSMENT_BROWSER_TENANT;
const otherTenant = process.env.ASSESSMENT_BROWSER_OTHER_TENANT;
test.beforeAll(() => {
  if (
    process.env.ASSESSMENT_CANDIDATE_BROWSER_GATE !== "1" ||
    !password ||
    !candidate ||
    !tenant ||
    !otherTenant
  )
    throw new Error(
      "Run scripts/verify_candidate_browser.py with a disposable PostgreSQL fixture.",
    );
});
async function login(page: Page, email = candidate!) {
  await page.goto("/");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.getByLabel("Institution", { exact: true }).selectOption(tenant!);
  await expect(
    page.getByRole("heading", { name: "My invitations" }),
  ).toBeVisible();
}
async function open(page: Page, title: string) {
  await page
    .getByRole("button", { name: `View invitation: ${title}`, exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Invitation details" }),
  ).toBeFocused();
}
function safe(value: unknown) {
  if (Array.isArray(value)) value.forEach(safe);
  else if (value && typeof value === "object")
    for (const [key, child] of Object.entries(value)) {
      expect([
        "content",
        "policy",
        "rubric",
        "correct_option_id",
        "correct_option_ids",
        "accommodation_reason",
        "reason",
        "candidate_user_id",
        "email",
      ]).not.toContain(key);
      safe(child);
    }
}
test("candidate inbox: safe traffic, acknowledgement, paging and memory-only session", async ({
  page,
}) => {
  const requests: string[] = [],
    errors: string[] = [];
  const checks: Promise<void>[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (r.url().includes("/api/v1/")) requests.push(r.url());
  });
  page.on("response", (r) => {
    if (r.url().includes("/exam-invitations") && r.ok())
      checks.push(
        r.json().then((body) => {
          safe(body);
          expect(JSON.stringify(body)).not.toContain("PRIVATE_");
        }),
      );
  });
  await login(page);
  await expect(
    page.getByRole("button", { name: "Question bank", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Approved versions", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /View invitation:/ }),
  ).toHaveCount(10);
  await open(page, "Invitation 01");
  await expect(page.getByText("40 minutes", { exact: true })).toBeVisible();
  await expect(page.getByText("The sitting has not opened yet.")).toBeVisible();
  await expect(page.getByRole("button", { name: /start exam/i })).toHaveCount(
    0,
  );
  await page
    .getByRole("button", { name: "Acknowledge invitation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Invitation acknowledged", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to invitations" }).click();
  await page.getByRole("button", { name: "Next invitations" }).click();
  await expect(page.getByText("Page 2", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: /View invitation:/ }),
  ).toHaveCount(4);
  await expect(
    page.getByRole("button", { name: "Next invitations" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Previous invitations" }).click();
  await expect(page.getByText("Page 1", { exact: true })).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => ({
      local: Object.keys(localStorage),
      session: Object.keys(sessionStorage),
    })),
  ).toEqual({ local: [], session: [] });
  await login(page);
  await open(page, "Invitation 01");
  await expect(
    page.getByRole("heading", { name: "Invitation acknowledged", exact: true }),
  ).toBeVisible();
  await Promise.all(checks);
  expect(
    requests.some((url) => /question|publication|taxonomy/.test(url)),
  ).toBe(false);
  expect(errors).toEqual([]);
});
test("lost response after commit: same acknowledgement recovers one receipt", async ({
  page,
}) => {
  await login(page);
  await open(page, "Invitation 02");
  let lost = false;
  await page.route("**/exam-invitations/*/accept", async (route) => {
    if (!lost) {
      lost = true;
      const saved = await route.fetch();
      expect(saved.status()).toBe(200);
      await route.abort("connectionfailed");
    } else await route.continue();
  });
  await page
    .getByRole("button", { name: "Acknowledge invitation", exact: true })
    .click();
  await expect(
    page.getByRole("alert", { name: "Invitation request error" }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Retry same acknowledgement" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Invitation acknowledged", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry same acknowledgement" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Refresh invitations" }).click();
  await expect(
    page.getByRole("heading", { name: "Invitation acknowledged", exact: true }),
  ).toBeVisible();
});
test("terminal states, historical receipt and narrow keyboard detail", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByRole("button", { name: "Next invitations" }).click();
  await open(page, "Invitation 12");
  await expect(
    page.getByText("This sitting has been cancelled."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Acknowledge invitation", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Back to invitations" }).click();
  await open(page, "Invitation 13");
  await expect(
    page.getByText("Your registration has been withdrawn."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Acknowledge invitation", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Back to invitations" }).click();
  await page
    .getByRole("button", {
      name: "View invitation: Invitation 14",
      exact: true,
    })
    .focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("region", { name: "Invitation details" }),
  ).toBeFocused();
  await expect(page.getByText("50 minutes", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/registration changed after this acknowledgement/),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await expect(page.locator("body")).not.toContainText("PRIVATE_");
});
test("tenant switch discards late detail and another candidate sees only their registration", async ({
  page,
}) => {
  await login(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let reached!: () => void;
  const started = new Promise<void>((resolve) => {
    reached = resolve;
  });
  await page.route("**/exam-invitations/*", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    reached();
    await gate;
    await route.fulfill({ response });
  });
  await page
    .getByRole("button", {
      name: "View invitation: Invitation 03",
      exact: true,
    })
    .click();
  await started;
  await page
    .getByLabel("Institution", { exact: true })
    .selectOption(otherTenant!);
  await expect(
    page.getByRole("heading", { name: "No invitations on this page" }),
  ).toBeVisible();
  release();
  await page.unrouteAll({ behavior: "wait" });
  await expect(
    page.getByRole("region", { name: "Invitation details" }),
  ).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("Invitation 03");
  await page.getByRole("button", { name: "Sign out" }).click();
  await login(page, process.env.ASSESSMENT_BROWSER_OTHER_CANDIDATE!);
  await expect(
    page.getByRole("button", { name: /View invitation:/ }),
  ).toHaveCount(1);
  await open(page, "Invitation 01");
  await expect(page.getByText("30 minutes", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Invitation acknowledged", exact: true }),
  ).toHaveCount(0);
});
test("session expiration clears invitation data", async ({ page }) => {
  await login(page);
  await page.route("**/exam-invitations?**", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/problem+json",
      body: JSON.stringify({ code: "invalid_session" }),
    }),
  );
  await page.getByRole("button", { name: "Refresh invitations" }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Invitation 01");
});
