import { expect, test, type Page } from "@playwright/test";

/** Opens the site and waits until it's interactive (the key figures load after hydration). */
async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("kpis")).toBeVisible();
}

test("answers a starter question with the query, results and a streamed answer", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /occupancy, ADR and RevPAR/ }).click();

  const answer = page.getByTestId("assistant-message");
  // The steps are folded under "How I worked it out"; each is a card with the row count, and
  // expanding it shows the inputs and the result table.
  await expect(answer.getByTestId("how")).toContainText("How I worked it out · 1 step");
  await answer.getByTestId("how").locator("summary").first().click();
  const card = answer.locator("details details", { hasText: "Fetched KPIs" });
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
  await open(page);
  const box = page.getByLabel("Message");
  await box.fill("How is occupancy?");
  await box.press("Enter");
  await expect(page.getByTestId("assistant-message").first()).toContainText("tokens in");

  await box.fill("Which channels cancel most?");
  await box.press("Enter");
  const second = page.getByTestId("assistant-message").nth(1);
  await second.getByTestId("how").locator("summary").first().click();
  const card = second.locator("details details", { hasText: "Ran a SQL query" });
  await card.locator("summary").click();
  await expect(card.locator("pre")).toContainText("FROM v_channel_mix");
  await expect(card).toContainText("7 rows");
  await expect(second).toContainText("tokens in");

  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByText("What would you like to know?")).toBeVisible();
});

test("answers end with actions and follow-up questions", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page);
  const box = page.getByLabel("Message");
  await box.fill("How is occupancy for the actions test?");
  await box.press("Enter");
  const answer = page.getByTestId("assistant-message");
  const actions = answer.getByTestId("answer-actions");
  await expect(actions).toBeVisible();
  // No dataset ids or raw suggestion block in the visible answer.
  await expect(answer.locator(".markdown")).not.toContainText("suggestions");

  await actions.getByRole("button", { name: "Copy" }).click();
  await expect(actions.getByRole("button", { name: "Copied" })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("Here is what the database shows");

  const saved = page.waitForResponse((r) => r.url().endsWith("/api/feedback") && r.status() === 204);
  await actions.getByRole("button", { name: "Useful", exact: true }).click();
  await saved;
  await page.reload();
  await expect(page.getByTestId("answer-actions").getByRole("button", { name: "Useful", exact: true }))
    .toHaveAttribute("aria-pressed", "true");

  // A follow-up question asks the next one.
  await page.getByTestId("suggestions").getByRole("button", { name: /Which booking channels/ }).click();
  await expect(page.getByTestId("assistant-message").nth(1)).toContainText("Ran a SQL query");
  // Only the last answer offers follow-ups.
  await expect(page.getByTestId("suggestions")).toHaveCount(1);
});

test("an answer saves as a report that runs again from the sidebar", async ({ page }) => {
  await open(page);
  const box = page.getByLabel("Message");
  await box.fill("How is occupancy for the saved test?");
  await box.press("Enter");
  await page.getByTestId("answer-actions").getByRole("button", { name: "Save as report" }).click();
  const dialog = page.getByRole("dialog", { name: "Save as report" });
  await expect(dialog).toContainText("How is occupancy for the saved test?");
  // Without SMTP it can't be emailed: only "open it myself".
  await expect(dialog.getByRole("radio", { name: /Every day/ })).toBeDisabled();
  await expect(dialog).toContainText("To get it by email");
  await dialog.getByLabel("Name").fill("Saved test");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toHaveCount(0);

  const reports = page.getByTestId("reports");
  await expect(reports.getByRole("button", { name: "Run “Saved test”" })).toBeVisible();
  await page.getByRole("button", { name: "New chat" }).click();
  await reports.getByRole("button", { name: "Run “Saved test”" }).click();
  // A fresh conversation with the saved question.
  await expect(page.getByTestId("assistant-message")).toHaveCount(1);
  await expect(page.getByTestId("assistant-message")).toContainText("Here is what the database shows");
  await expect(page.locator("main, .flex-1").getByText("How is occupancy for the saved test?", { exact: true }).first()).toBeVisible();

  // Renamed, then deleted.
  await reports.getByRole("button", { name: "Edit “Saved test”" }).click();
  await page.getByRole("dialog").getByLabel("Name").fill("Saved test, renamed");
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(reports.getByRole("button", { name: "Run “Saved test, renamed”" })).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await reports.getByRole("button", { name: "Delete “Saved test, renamed”" }).click();
  await expect(page.getByTestId("reports")).toHaveCount(0);
});

test("the home screen shows the key figures, recommendations and questions", async ({ page }) => {
  await open(page);
  // Key figures for the picked hotel; picking another one is remembered.
  const kpis = page.getByTestId("kpis");
  await expect(kpis.getByRole("listitem")).toHaveCount(7);
  await expect(kpis).toContainText("Occupancy today");
  await expect(kpis).toContainText("Gross Revenue");
  await expect(kpis).toContainText(/€\d/);
  await expect(page.getByTestId("data-freshness")).toContainText("Sample data");
  await page.getByLabel("Hotel", { exact: true }).selectOption("OPO");
  await expect(page.getByLabel("Message")).toHaveAttribute("placeholder", /Douro Plaza Hotel/);
  await page.reload();
  await expect(page.getByLabel("Hotel", { exact: true })).toHaveValue("OPO");
  await page.getByLabel("Hotel", { exact: true }).selectOption("LIS");

  // Recommendations: marked done and voted on, and still so after a reload.
  const section = page.getByTestId("recommendations");
  await expect(section.getByRole("heading", { name: "Today's recommendations:" })).toBeVisible();
  const first = section.getByRole("listitem").first();
  await expect(first).toContainText("Cut OTA cancellations");
  await expect(first).toContainText("€18,400 at risk");
  await expect(section.getByRole("listitem")).toHaveCount(3);
  const saved = () => page.waitForResponse((r) => r.url().endsWith("/api/feedback") && r.status() === 204);
  await Promise.all([saved(), first.getByRole("button", { name: "Done" }).click()]);
  await Promise.all([saved(), first.getByRole("button", { name: "Useful", exact: true }).click()]);
  await expect(first.getByRole("button", { name: "Useful", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByTestId("recommendations").getByRole("listitem").first().getByRole("button", { name: "Done" }))
    .toHaveAttribute("aria-pressed", "true");

  // Questions grouped by topic.
  const questions = page.getByRole("region", { name: "What would you like to know?" });
  await expect(questions.getByRole("button", { name: /occupancy, ADR and RevPAR/ })).toHaveCount(1);
  await page.getByRole("tab", { name: "Charts & documents" }).click();
  await expect(questions.getByRole("button", { name: /to Excel/ })).toBeVisible();
  await expect(questions.getByRole("button", { name: /occupancy, ADR and RevPAR/ })).toHaveCount(0);

  // A recommendation opens its analysis.
  await page.getByTestId("recommendations").getByRole("button", { name: "See the analysis" }).first().click();
  await expect(page.getByText("Which booking channels have the highest cancellation rates this year?").last()).toBeVisible();
  await expect(page.getByTestId("assistant-message")).toContainText("Ran a SQL query");
});

test("the period picker changes the key figures and is remembered", async ({ page }) => {
  await open(page);
  const kpis = page.getByTestId("kpis");
  await expect(kpis).toContainText("ADR · this month");
  const picker = page.getByLabel("Period", { exact: true }).filter({ visible: true });
  await picker.selectOption("ytd");
  await expect(kpis).toContainText("ADR · this year");
  await expect(kpis).toContainText("Room revenue · this year");
  await expect(kpis).toContainText("Gross Revenue · this year");
  await page.reload();
  await expect(page.getByTestId("kpis")).toContainText("ADR · this year");
  await page.getByLabel("Period", { exact: true }).filter({ visible: true }).selectOption("mtd");
  await expect(page.getByTestId("kpis")).toContainText("ADR · this month");
});

test("the bell lists the hotel's alerts", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /^Alerts/ }).click();
  const list = page.getByTestId("alerts");
  await expect(list).toContainText("Alerts · Tagus Riverside Hotel");
  await expect(page.getByTestId("alerts-badge")).toHaveCount(0); // seen once opened
  const first = list.getByRole("button").first();
  if (await first.count()) {
    await first.click();
    await expect(page.getByTestId("assistant-message")).toBeVisible();
  } else {
    await expect(list).toContainText("No alerts today");
  }
});

test("a key figure asks about itself", async ({ page }) => {
  await open(page);
  await page.getByTestId("kpis").getByRole("button", { name: /Arrivals · Departures/ }).click();
  await expect(page.getByText(/Who arrives and who leaves .* today\?/).last()).toBeVisible();
});

test("the Home button goes back to the start page", async ({ page }) => {
  await open(page);
  const home = page.getByRole("button", { name: "Home", exact: true });
  await expect(home).toHaveAttribute("aria-current", "page");
  const box = page.getByLabel("Message");
  await box.fill("How is occupancy for the home test?");
  await box.press("Enter");
  await expect(page.getByTestId("answer-actions")).toBeVisible();
  await expect(page.getByTestId("kpis")).toHaveCount(0);
  await home.click();
  await expect(page.getByTestId("kpis")).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
  // The logo goes there too.
  await page.getByRole("complementary", { name: "Conversations" })
    .getByRole("button", { name: /^How is occupancy for the home test\?/ }).click();
  await expect(page.getByTestId("kpis")).toHaveCount(0);
  await page.getByRole("button", { name: "Hotel Super Intelligence: Home" }).click();
  await expect(page.getByTestId("kpis")).toBeVisible();
});

test("Stop cancels a streaming answer", async ({ page }) => {
  await open(page);
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
  await open(page);
  const box = page.getByLabel("Message");
  await box.fill("Please refuse this");
  await box.press("Enter");
  const alert = page.getByTestId("assistant-message").getByRole("alert");
  await expect(alert).toContainText("declined");
  await expect(alert).toContainText("not added to the conversation");
});

test("charts render inline with tooltips, a data table and a PNG download", async ({ page }) => {
  await open(page);
  const box = page.getByLabel("Message");
  await box.fill("Make a chart of monthly occupancy by hotel");
  await box.press("Enter");

  const chart = page.getByTestId("chart");
  await expect(chart).toBeVisible();
  const canvas = chart.getByTestId("chart-canvas");
  await expect(canvas.locator("svg")).toContainText("Occupancy by hotel");
  await expect(canvas.locator("svg")).toContainText("LIS");  // legend
  await expect(page.getByTestId("assistant-message")).toContainText("peaked in summer");

  // Pointing at a point shows its values.
  const point = await canvas.locator(".mark-symbol path").nth(5).boundingBox();
  await page.mouse.move(point!.x + point!.width / 2, point!.y + point!.height / 2, { steps: 5 });
  const tooltip = page.locator("#vg-tooltip-element");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText(/(October|November|December) 2025/);
  await expect(tooltip).toContainText("Hotel");
  await expect(tooltip).toContainText("%");

  await chart.getByRole("button", { name: "Show data" }).click();
  await expect(chart.locator("tbody tr")).toHaveCount(12);
  await expect(chart.locator("thead th")).toHaveText(["Period", "BCN", "LIS", "OPO"]);

  // The same chart as bars, then back to lines.
  const types = chart.getByRole("group", { name: "Chart type" });
  await expect(types.getByRole("button", { name: "Lines" })).toHaveAttribute("aria-pressed", "true");
  await types.getByRole("button", { name: "Bars" }).click();
  await expect(canvas.locator(".mark-rect path").first()).toBeVisible();
  await expect(canvas.locator("svg")).toContainText("Occupancy by hotel");
  await types.getByRole("button", { name: "Lines" }).click();
  await expect(canvas.locator(".mark-rect path")).toHaveCount(0);

  // Full screen, closed with Escape.
  await chart.getByRole("button", { name: "Full screen" }).click();
  const dialog = page.getByRole("dialog", { name: "Occupancy by hotel" });
  await expect(dialog.getByTestId("chart-canvas").locator("svg")).toContainText("Occupancy by hotel");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  const href = await chart.getByRole("link", { name: "Download PNG" }).getAttribute("href");
  const png = await page.request.get(href!);
  expect(png.status()).toBe(200);
  expect(png.headers()["content-type"]).toBe("image/png");
});

test("bar charts with a trend line and a second axis", async ({ page }) => {
  await open(page);
  const box = page.getByLabel("Message");
  await box.fill("Bar chart of monthly occupancy with a trend line");
  await box.press("Enter");
  const svg = page.getByTestId("chart-canvas").locator("svg");
  await expect(svg).toContainText("Occupancy and ADR");
  await expect(svg.locator(".mark-rect path")).toHaveCount(12);  // the bars
  await expect(svg.locator(".mark-line path")).toHaveCount(2);  // the trend and the ADR line
  await expect(svg).toContainText("ADR");  // right-hand axis title
  await expect(page.getByTestId("assistant-message")).toContainText("trend line");
});

for (const [prompt, ext, magic] of [
  ["Export the monthly KPIs to Excel", "xlsx", "PK"],
  ["Build a Q3 deck for the owners", "pptx", "PK"],
  ["Write an occupancy report", "pdf", "%PDF"],
] as const) {
  test(`creates a downloadable ${ext}`, async ({ page }) => {
    await open(page);
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
  await open(page);
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
  await expect(answer.locator("details details", { hasText: "Fetched KPIs" })).toContainText("3 rows");
  await expect(answer).toContainText("tokens in");
  await expect(page.getByText("How is occupancy for the sidebar test?", { exact: true }).last()).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("assistant-message")).toContainText("tokens in");

  // Pin and rename it; search finds it by its new name.
  await sidebar.getByRole("button", { name: /^Pin “How is occupancy for the sidebar test\?”/ }).click();
  await expect(sidebar.getByRole("heading", { name: "Pinned" })).toBeVisible();
  page.once("dialog", (d) => d.accept("Sidebar test, renamed"));
  await sidebar.getByRole("button", { name: /^Rename “How is occupancy for the sidebar test\?”/ }).click();
  const renamed = sidebar.getByRole("button", { name: /^Sidebar test, renamed/ });
  await expect(renamed).toBeVisible();
  await sidebar.getByLabel("Search conversations").fill("renamed");
  await expect(renamed).toBeVisible();
  await sidebar.getByLabel("Search conversations").fill("nothing like this");
  await expect(sidebar).toContainText("No conversations match.");
  await sidebar.getByLabel("Search conversations").fill("");

  page.once("dialog", (d) => d.accept());
  await sidebar.getByRole("button", { name: /Delete “Sidebar test, renamed”/ }).click();
  await expect(renamed).toHaveCount(0);
  await expect(page.getByText("What would you like to know?")).toBeVisible();
});

test("on phones the key figures fit on screen without trend lines", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const kpis = page.getByTestId("kpis");
  const box = await kpis.boundingBox();
  expect(box!.y + box!.height).toBeLessThan(844); // all seven, no swiping
  expect(box!.width).toBeLessThanOrEqual(390);
  await expect(kpis.locator("svg")).toHaveCount(6); // the trend lines are there (arrivals has none)...
  for (const line of await kpis.locator("svg").all()) await expect(line).toBeHidden(); // ...but hidden
  const questions = page.getByRole("region", { name: "What would you like to know?" });
  await expect(questions.locator("button:visible").filter({ hasNotText: /^(All|Occupancy|Rates|Channels|Bookings|Forecast|Charts & documents)$/ })).toHaveCount(4);
  await expect(page.getByRole("button", { name: "New chat" })).toBeVisible(); // in the header
});

test("on phones the conversation list opens as a drawer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await open(page);
  const sidebar = page.getByRole("complementary", { name: "Conversations" });
  await expect(sidebar).toBeHidden();
  await page.getByRole("button", { name: "Show conversations" }).click();
  await expect(sidebar).toBeVisible();
  await sidebar.getByRole("button", { name: "Close" }).click();
  await expect(sidebar).toBeHidden();
});

test.describe("in Latin American Spanish", () => {
  test.use({ locale: "es-MX" });

  test("follows the browser language, answers in Spanish, and remembers the switch", async ({ page }) => {
    await open(page);
    await expect(page.locator("html")).toHaveAttribute("lang", "es-419");
    await expect(page.getByRole("heading", { name: "¿Qué te gustaría saber?" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recomendaciones del día:" })).toBeVisible();
    await expect(page.getByTestId("recommendations")).toContainText("Reducir las cancelaciones de OTA");

    await page.getByRole("button", { name: /¿Qué canales le traen/ }).click();
    const answer = page.getByTestId("assistant-message");
    await expect(answer.locator("details details", { hasText: "Ejecutó una consulta SQL" })).toContainText("7 filas");
    await expect(answer.getByTestId("how")).toContainText("Ver cómo lo calculé");
    await expect(page.getByTestId("suggestions")).toContainText("Compáralo con 2024");
    await expect(answer).toContainText("Esto es lo que muestra la base de datos");
    await expect(answer).toContainText("tokens de entrada");

    await page.getByRole("button", { name: "Menú de la cuenta" }).click();
    await page.getByLabel("Idioma").selectOption("en");
    await expect(page.getByRole("button", { name: "New chat" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await page.reload();
    await page.getByRole("button", { name: "Account menu" }).click();
    await expect(page.getByLabel("Language")).toHaveValue("en"); // the cookie beats the browser language
    await page.getByLabel("Language").selectOption("es");
    await page.reload();
    await expect(page.getByRole("button", { name: "Nuevo chat" })).toBeVisible();
  });

  test("charts get Spanish dates and controls", async ({ page }) => {
    await open(page);
    const box = page.getByLabel("Mensaje");
    await box.fill("Hazme un gráfico de la ocupación mensual");
    await box.press("Enter");
    const chart = page.getByTestId("chart");
    await expect(chart).toContainText("Ocupación por hotel");
    await chart.getByRole("button", { name: "Ver datos" }).click();
    await expect(chart.locator("tbody tr").first()).toContainText("octubre de 2025");
    await expect(chart.getByRole("link", { name: "Descargar PNG" })).toBeVisible();
    await expect(page.getByTestId("assistant-message")).toContainText("Los tres hoteles tuvieron su pico en verano.");
  });
});

test.describe("light and dark colors", () => {
  test.use({ colorScheme: "dark" }); // the system preference doesn't decide: light is the default

  test("starts light, switches to dark, and remembers the choice", async ({ page }) => {
    await open(page);
    const html = page.locator("html");
    const background = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    await expect(html).not.toHaveClass(/dark/);
    const light = await background();

    const menu = page.getByRole("button", { name: "Account menu" });
    await menu.click();
    await page.getByRole("button", { name: "Switch to dark mode" }).click();
    await expect(html).toHaveClass(/dark/);
    expect(await background()).not.toBe(light);

    await page.reload();
    await expect(html).toHaveClass(/dark/); // rendered dark by the server, no flash of light
    await menu.click();
    await page.getByRole("button", { name: "Switch to light mode" }).click();
    await expect(html).not.toHaveClass(/dark/);
    await page.reload();
    await menu.click();
    await expect(page.getByRole("button", { name: "Switch to dark mode" })).toBeVisible();
    expect(await background()).toBe(light);
  });
});

test("rate-limits chat messages and says when to retry", async ({ request }) => {
  // The test server allows 20 messages per 10 minutes per client; earlier tests used some.
  let status = 200;
  let body: { detail?: string } = {};
  for (let i = 0; i < 21 && status !== 429; i++) {
    const r = await request.post("/api/chat", { data: { message: "" } }); // rejected by the agent, still counted
    status = r.status();
    if (status === 429) body = await r.json();
  }
  expect(status).toBe(429);
  expect(body.detail).toMatch(/Try again in \d+ seconds/);
});
