import { expect, test, type Page } from "@playwright/test";
import { ACCOUNTS_ADMIN } from "../playwright.config";

// Runs against the instance with user accounts (WEB_AUTH=password) and an MCP server that takes
// hotel access from the user directory: an administrator creates a user for one hotel, and that
// user's answers only ever include that hotel.

const user = { name: "Lis Only", email: `lis-${Date.now()}@accounts.test`, password: "lis-password-123" };

async function signIn(page: Page, login: string, password: string) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Email or ID").fill(login);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function askForKpis(page: Page) {
  await expect(page.getByTestId("kpis")).toBeVisible(); // interactive
  const box = page.getByLabel("Message");
  await box.fill("How did each hotel do last quarter?");
  await box.press("Enter");
  const answer = page.getByTestId("assistant-message").last();
  await expect(answer).toContainText("tokens in");
  return answer;
}

test("administrators manage users, and users see only their hotels", async ({ page }) => {
  await signIn(page, ACCOUNTS_ADMIN.email, "not-the-password");
  await expect(page.getByRole("alert").filter({ hasText: "Wrong email or password." })).toBeVisible();

  // The administrator sees every hotel.
  await signIn(page, ACCOUNTS_ADMIN.email, ACCOUNTS_ADMIN.password);
  const all = await askForKpis(page);
  for (const code of ["LIS", "BCN", "OPO"]) await expect(all.getByRole("cell", { name: code, exact: true })).toBeVisible();

  // ...and creates a user for Lisbon only.
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("link", { name: "Admin" }).click();
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  await page.getByRole("button", { name: "New user" }).click();
  await page.getByLabel("Name").fill(user.name);
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Phone").fill("+351 912 345 678");
  await page.getByLabel("Unique ID").fill(`EMP-${Date.now()}`);
  await page.getByLabel("Notes").fill("Front office, Lisbon");
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("checkbox", { name: /^LIS/ }).check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved." })).toBeVisible();
  await expect(page.getByRole("row", { name: new RegExp(user.email) })).toContainText("LIS");

  // Hotel IDs must be whole numbers above 0.
  await page.getByRole("tab", { name: "Hotels" }).click();
  const pmsId = page.getByLabel("PMS ID LIS");
  const original = await pmsId.inputValue();
  await pmsId.fill("0");
  await expect(page.getByRole("button", { name: "Save LIS" })).toBeDisabled();
  await pmsId.fill(original);

  await page.context().clearCookies();

  // The user sees Lisbon only, and has no administration.
  await signIn(page, user.email, user.password);
  const mine = await askForKpis(page);
  await expect(mine.getByRole("cell", { name: "LIS", exact: true })).toBeVisible();
  for (const code of ["BCN", "OPO"]) await expect(mine.getByRole("cell", { name: code, exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Account menu" }).click();
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Administrators only" })).toBeVisible();
  expect((await page.request.get("/api/admin/users")).status()).toBe(403);

  // Deleted users can't use the assistant any more, even with a session.
  await page.context().clearCookies();
  await signIn(page, ACCOUNTS_ADMIN.email, ACCOUNTS_ADMIN.password);
  await page.goto("/admin");
  await page.getByRole("button", { name: `Edit ${user.name}` }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete user" }).click();
  await expect(page.getByRole("row", { name: new RegExp(user.email) })).toHaveCount(0);
});
