import { expect, test } from "@playwright/test";

test("answers a starter question with the query, results and a streamed answer", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /occupancy, ADR and RevPAR/ }).click();

  const answer = page.getByTestId("assistant-message");
  // Tool step: collapsed card with the row count; expanding shows inputs and the result table.
  const card = answer.locator("details", { hasText: "Fetched KPIs" });
  await expect(card).toContainText("3 rows");
  await card.locator("summary").click();
  await expect(card).toContainText("2026-07-01");
  await expect(card.locator("tbody tr")).toHaveCount(3);
  await expect(card.locator("thead")).toContainText("occupancy");

  // Markdown answer rendered as a table, then the usage footer once done.
  await expect(answer.locator(".markdown table tbody tr")).toHaveCount(3);
  await expect(answer).toContainText("tokens in");
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
});

test("follow-up questions continue the conversation and show SQL", async ({ page }) => {
  await page.goto("/");
  const box = page.getByLabel("Message");
  await box.fill("How is occupancy?");
  await box.press("Enter");
  await expect(page.getByTestId("assistant-message").first()).toContainText("tokens in");

  await box.fill("Which channels cancel most?");
  await box.press("Enter");
  const second = page.getByTestId("assistant-message").nth(1);
  const card = second.locator("details", { hasText: "Ran a SQL query" });
  await card.locator("summary").click();
  await expect(card.locator("pre")).toContainText("FROM v_channel_mix");
  await expect(card).toContainText("7 rows");
  await expect(second).toContainText("tokens in");

  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByText("What would you like to know?")).toBeVisible();
});

test("Stop cancels a streaming answer", async ({ page }) => {
  await page.goto("/");
  const box = page.getByLabel("Message");
  await box.fill("Give me a slow answer");
  await box.press("Enter");
  const answer = page.getByTestId("assistant-message");
  await expect(answer).toContainText("streams slowly");
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(answer).toContainText("Stopped.");
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
});

test("shows refusals as a failed message", async ({ page }) => {
  await page.goto("/");
  const box = page.getByLabel("Message");
  await box.fill("Please refuse this");
  await box.press("Enter");
  const alert = page.getByTestId("assistant-message").getByRole("alert");
  await expect(alert).toContainText("declined");
  await expect(alert).toContainText("not added to the conversation");
});

test("charts render inline with hover values, a data table and a PNG download", async ({ page }) => {
  await page.goto("/");
  const box = page.getByLabel("Message");
  await box.fill("Make a chart of monthly occupancy by hotel");
  await box.press("Enter");

  const chart = page.getByTestId("chart");
  await expect(chart).toBeVisible();
  await expect(chart.locator("svg").filter({ visible: true })).toContainText("Occupancy by hotel");
  await expect(page.getByTestId("assistant-message")).toContainText("peaked in summer");

  // Keyboard reaches the same values as hover.
  const hover = chart.getByTestId("chart-hover").filter({ visible: true });
  await hover.focus();
  await page.keyboard.press("ArrowRight");
  const tooltip = chart.getByRole("tooltip");
  await expect(tooltip).toContainText("October 2025");
  await expect(tooltip).toContainText("LIS");
  await expect(tooltip).toContainText("%");
  await hover.hover({ position: { x: 700, y: 200 } });
  await expect(tooltip).not.toContainText("October 2025");

  await chart.getByRole("button", { name: "Show data" }).click();
  await expect(chart.locator("tbody tr")).toHaveCount(12);

  const href = await chart.getByRole("link", { name: "Download PNG" }).getAttribute("href");
  const png = await page.request.get(href!);
  expect(png.status()).toBe(200);
  expect(png.headers()["content-type"]).toBe("image/png");
});

for (const [prompt, ext, magic] of [
  ["Export the monthly KPIs to Excel", "xlsx", "PK"],
  ["Build a Q3 deck for the owners", "pptx", "PK"],
  ["Write an occupancy report", "pdf", "%PDF"],
] as const) {
  test(`creates a downloadable ${ext}`, async ({ page }) => {
    await page.goto("/");
    const box = page.getByLabel("Message");
    await box.fill(prompt);
    await box.press("Enter");
    const card = page.getByTestId("artifact");
    await expect(card).toContainText(`.${ext}`);
    await expect(page.getByTestId("assistant-message")).toContainText("tokens in");

    const downloadPromise = page.waitForEvent("download");
    await card.getByRole("link", { name: "Download" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(new RegExp(`\\.${ext}$`));
    const fs = await import("node:fs/promises");
    const bytes = await fs.readFile((await download.path())!);
    expect(bytes.subarray(0, magic.length).toString()).toBe(magic);
  });
}

test("saves conversations to reopen, reload and delete from the sidebar", async ({ page }) => {
  await page.goto("/");
  const box = page.getByLabel("Message");
  await box.fill("How is occupancy for the sidebar test?");
  await box.press("Enter");
  await expect(page.getByTestId("assistant-message")).toContainText("tokens in");
  await expect(page).toHaveURL(/\?c=conv_[0-9a-f]{16}$/);

  const sidebar = page.getByRole("complementary", { name: "Conversations" });
  const item = sidebar.getByRole("button", { name: /^How is occupancy for the sidebar test\?/ });
  await expect(item).toHaveAttribute("aria-current", "true");
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByText("What would you like to know?")).toBeVisible();
  await expect(page).toHaveURL(/\/$/);

  // Reopening replays the saved answer: tool step, results and the answer text.
  await item.click();
  const answer = page.getByTestId("assistant-message");
  await expect(answer.locator("details", { hasText: "Fetched KPIs" })).toContainText("3 rows");
  await expect(answer).toContainText("tokens in");
  await expect(page.getByText("How is occupancy for the sidebar test?", { exact: true }).last()).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("assistant-message")).toContainText("tokens in");

  page.once("dialog", (d) => d.accept());
  await sidebar.getByRole("button", { name: /Delete “How is occupancy for the sidebar test\?”/ }).click();
  await expect(item).toHaveCount(0);
  await expect(page.getByText("What would you like to know?")).toBeVisible();
});

test("on phones the conversation list opens as a drawer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  const sidebar = page.getByRole("complementary", { name: "Conversations" });
  await expect(sidebar).toBeHidden();
  await page.getByRole("button", { name: "Show conversations" }).click();
  await expect(sidebar).toBeVisible();
  await sidebar.getByRole("button", { name: "Close" }).click();
  await expect(sidebar).toBeHidden();
});

test("rate-limits chat messages and says when to retry", async ({ request }) => {
  // The test server allows 16 messages per 10 minutes per client; earlier tests used some.
  let status = 200;
  let body: { detail?: string } = {};
  for (let i = 0; i < 17 && status !== 429; i++) {
    const r = await request.post("/api/chat", { data: { message: "" } }); // rejected by the agent, still counted
    status = r.status();
    if (status === 429) body = await r.json();
  }
  expect(status).toBe(429);
  expect(body.detail).toMatch(/Try again in \d+ seconds/);
});
