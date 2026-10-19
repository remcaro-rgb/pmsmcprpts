import { defineConfig, devices } from "@playwright/test";

// Browser tests run the production build against the real agent service, MCP server and
// database, with a scripted stand-in for Claude (e2e/fake_agent.py). Needs a seeded database:
//   PMS_DATABASE_URL=postgresql://pms_readonly:pms_readonly@localhost:5432/pms npm run build && npm run e2e
const AGENT_PORT = 8101;
const WEB_PORT = 3100;
// A second instance with sign-in on, against a test identity provider (e2e/fake_oidc.py).
const OIDC_PORT = 8102;
const AUTH_WEB_PORT = 3101;
// A third with user accounts (WEB_AUTH=password), when the user directory is available:
//   PMS_TEST_APP_DATABASE_URL=postgresql://pms_app:...@localhost:5432/pms
// Its MCP server runs with PMS_USER_DIRECTORY=true, so each user sees only their hotels.
const APP_DSN = process.env.PMS_TEST_APP_DATABASE_URL;
const ACCOUNTS_MCP_PORT = 8103;
const ACCOUNTS_AGENT_PORT = 8104;
const ACCOUNTS_WEB_PORT = 3102;
const SERVICE_TOKEN = "e2e-service-token-0123456789abcdef0123";
export const ACCOUNTS_ADMIN = { email: "admin@accounts.test", password: "admin-password-e2e" };

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  projects: [
    { name: "chat", testMatch: "chat.spec.ts", use: { baseURL: `http://127.0.0.1:${WEB_PORT}` } },
    { name: "sign-in", testMatch: "auth.spec.ts", use: { baseURL: `http://localhost:${AUTH_WEB_PORT}` } },
    ...(APP_DSN
      ? [{ name: "accounts", testMatch: "accounts.spec.ts", use: { baseURL: `http://localhost:${ACCOUNTS_WEB_PORT}` } }]
      : []),
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
      env: { PMS_MCP_URL: "", PMS_APP_DATABASE_URL: "" },
      reuseExistingServer: !process.env.CI,
    },
    {
      // The same standalone server the Docker image runs (needs `npm run build`).
      command: "node .next/standalone/server.js",
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: {
        AGENT_URL: `http://127.0.0.1:${AGENT_PORT}`, PORT: String(WEB_PORT), HOSTNAME: "127.0.0.1",
        CHAT_RATE_LIMIT: "20/600",
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
        PMS_ALLOWED_EMAILS: "ann@hotel.example,bob@hotel.example",
      },
      reuseExistingServer: !process.env.CI,
    },
    ...(APP_DSN ? accountsServers(APP_DSN) : []),
  ],
});

function accountsServers(appDsn: string): { command: string; url: string; env: Record<string, string>; reuseExistingServer: boolean }[] {
  const mcp = `http://127.0.0.1:${ACCOUNTS_MCP_PORT}`;
  const agent = `http://127.0.0.1:${ACCOUNTS_AGENT_PORT}`;
  return [
    {
      command: `python3 -m pms_mcp --transport streamable-http --port ${ACCOUNTS_MCP_PORT}`,
      url: `${mcp}/mcp`,
      env: { PYTHONPATH: "../mcp_server", PMS_USER_DIRECTORY: "true", PMS_MCP_SERVICE_TOKEN: SERVICE_TOKEN, PMS_RATE_LIMIT: "off" },
      reuseExistingServer: !process.env.CI,
    },
    {
      // Creates (or resets) the administrator, then runs the agent with accounts on.
      command:
        `echo "${ACCOUNTS_ADMIN.password}" | python3 -m pms_agent.admin create-admin --email ${ACCOUNTS_ADMIN.email} ` +
        `--name "E2E Admin" --password-stdin && python3 e2e/fake_agent.py --port ${ACCOUNTS_AGENT_PORT}`,
      url: `${agent}/api/health`,
      env: {
        PYTHONPATH: "../agent", PMS_MCP_URL: `${mcp}/mcp`, PMS_MCP_TOKEN: SERVICE_TOKEN, PMS_APP_DATABASE_URL: appDsn,
      },
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "node .next/standalone/server.js",
      url: `http://127.0.0.1:${ACCOUNTS_WEB_PORT}/login`,
      env: {
        AGENT_URL: agent, PORT: String(ACCOUNTS_WEB_PORT), HOSTNAME: "127.0.0.1",
        WEB_AUTH: "password",
        WEB_SESSION_SECRET: "test-session-secret-0123456789abcdef",
      },
      reuseExistingServer: !process.env.CI,
    },
  ];
}
