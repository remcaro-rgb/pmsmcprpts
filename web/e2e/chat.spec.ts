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
