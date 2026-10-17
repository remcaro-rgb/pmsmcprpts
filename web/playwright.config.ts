import { defineConfig, devices } from "@playwright/test";

// Browser tests run the production build against the real agent service, MCP server and
// database, with a scripted stand-in for Claude (e2e/fake_agent.py). Needs a seeded database:
//   PMS_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms npm run build && npm run e2e
const AGENT_PORT = 8101;
const WEB_PORT = 3100;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
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
  ],
});
