import { defineConfig, devices } from "@playwright/test";

// Browser tests run the production build against the real agent service, MCP server and
// database, with a scripted stand-in for Claude (e2e/fake_agent.py). Needs a seeded database:
//   PMS_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms npm run build && npm run e2e
const AGENT_PORT = 8101;
const WEB_PORT = 3100;
// A second instance with sign-in on, against a test identity provider (e2e/fake_oidc.py).
const OIDC_PORT = 8102;
const AUTH_WEB_PORT = 3101;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  projects: [
    { name: "chat", testMatch: "chat.spec.ts", use: { baseURL: `http://127.0.0.1:${WEB_PORT}` } },
    { name: "sign-in", testMatch: "auth.spec.ts", use: { baseURL: `http://localhost:${AUTH_WEB_PORT}` } },
  ],
  use: {
    ...devices["Desktop Chrome"],
    // Use a preinstalled Chromium when the pinned Playwright browser is not downloaded.
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  webServer: [
    {
      command: `python3 e2e/fake_agent.py --port ${AGENT_PORT}`,
      url: `http://127.0.0.1:${AGENT_PORT}/api/health`,
      reuseExistingServer: !process.env.CI,
    },
    {
      // The same standalone server the Docker image runs (needs `npm run build`).
      command: "node .next/standalone/server.js",
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: {
        AGENT_URL: `http://127.0.0.1:${AGENT_PORT}`, PORT: String(WEB_PORT), HOSTNAME: "127.0.0.1",
        CHAT_RATE_LIMIT: "12/600",
      },
      reuseExistingServer: !process.env.CI,
    },
    {
      command: `python3 e2e/fake_oidc.py --port ${OIDC_PORT} --client-id web --client-secret web-test-secret`,
      url: `http://127.0.0.1:${OIDC_PORT}/.well-known/openid-configuration`,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "node .next/standalone/server.js",
      url: `http://127.0.0.1:${AUTH_WEB_PORT}/signed-out`,
      env: {
        AGENT_URL: `http://127.0.0.1:${AGENT_PORT}`, PORT: String(AUTH_WEB_PORT), HOSTNAME: "127.0.0.1",
        WEB_AUTH: "oidc",
        WEB_PUBLIC_URL: `http://localhost:${AUTH_WEB_PORT}`,
        WEB_SESSION_SECRET: "test-session-secret-0123456789abcdef",
        PMS_OIDC_ISSUER: `http://127.0.0.1:${OIDC_PORT}`,
        PMS_OIDC_ALLOW_HTTP: "true",
        WEB_OIDC_CLIENT_ID: "web",
        WEB_OIDC_CLIENT_SECRET: "web-test-secret",
        PMS_ALLOWED_EMAILS: "ann@hotel.example",
      },
      reuseExistingServer: !process.env.CI,
    },
  ],
});
