import { expect, test, type Page } from "@playwright/test";

// Runs against the instance with sign-in on (WEB_AUTH=oidc) and the test identity provider,
// which signs in as whatever email is typed. Only ann@hotel.example is on the allowlist.

async function signInAs(page: Page, email: string) {
  await expect(page.getByRole("heading", { name: "Test provider" })).toBeVisible();
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Continue" }).click();
}

test("signs in through the provider, chats, and signs out", async ({ page }) => {
  await page.goto("/");
  await signInAs(page, "ann@hotel.example");

  await expect(page.getByText("ann@hotel.example")).toBeVisible();
  const box = page.getByLabel("Message");
  await box.fill("How is occupancy?");
  await box.press("Enter");
  await expect(page.getByTestId("assistant-message")).toContainText("tokens in");

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "You're signed out" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Test provider" })).toBeVisible();
});

test("returns to the page that asked for sign-in", async ({ page }) => {
  await page.goto("/?from=link");
  await signInAs(page, "Ann@Hotel.example");
  await expect(page).toHaveURL(/\/\?from=link$/);
});

test("refuses accounts that are not on the allowlist", async ({ page }) => {
  await page.goto("/");
  await signInAs(page, "mallory@elsewhere.example");
  await expect(page.getByRole("heading", { name: "Access not allowed" })).toBeVisible();
  await expect(page.getByText("mallory@elsewhere.example is not allowed")).toBeVisible();
});

test("the API needs a session, and an identity header from the browser is ignored", async ({ request }) => {
  const anonymous = await request.post("/api/chat", {
    data: { message: "hi" },
    headers: { "x-pms-user": "ann@hotel.example" },
  });
  expect(anonymous.status()).toBe(401);
  expect(await anonymous.json()).toEqual({ detail: "Sign in to continue." });

  const forged = await request.post("/api/chat", {
    data: { message: "hi" },
    headers: { cookie: "pms_session=not-a-real-session" },
  });
  expect(forged.status()).toBe(401);
});

test("a callback without a pending sign-in asks to start again", async ({ page }) => {
  await page.goto("/auth/callback?code=abc&state=xyz");
  await expect(page.getByRole("heading", { name: "Sign-in expired" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in again" })).toBeVisible();
});
