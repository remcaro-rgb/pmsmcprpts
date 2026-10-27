# Prompt: clone this Mac's installation to an Ubuntu server

Paste the prompt below into **Claude Code running on your Mac**, started in the repository folder
(`cd ~/pmsmcprpts && claude`). It needs your Mac (where the data is) and SSH access to the server;
a cloud session can reach neither.

Give the secrets as environment variables when you start Claude Code, so they never appear in the
chat or its history:

```bash
cd ~/pmsmcprpts
export SERVER_PASSWORD='...'          # the server user's password (SSH and sudo)
export CLOUDFLARE_API_TOKEN='...'     # optional, see below
claude
```

`CLOUDFLARE_API_TOKEN` lets Claude create the tunnel and the DNS record for you. Create it at
dash.cloudflare.com → My Profile → API Tokens → Create Token → Custom token, with the permissions
**Account → Cloudflare Tunnel → Edit** and **Zone → DNS → Edit** (zone: goliatt.co). Without it,
Claude stops once and asks you to create the tunnel in the dashboard.

Fill in the three values at the top, then paste:

---

```text
Clone my local installation of this app (the Mac this session runs on, repository in the current
folder, running with docker compose) to a remote Ubuntu server, so that the server runs exactly
what my Mac runs now: same code, same database (the demo hotels AND the Fragata/FNS data, user
accounts, hotel assignments, saved reports, every table), same saved conversations, and the same
settings, published at https://aia-demo-cld.goliatt.co through a Cloudflare named tunnel.

Server: IP = <SERVER_IP>, SSH user = <SSH_USER>. The password is in the environment variable
SERVER_PASSWORD (for SSH and sudo). Cloudflare API token, if set: CLOUDFLARE_API_TOKEN.
Never print, log, commit or write these secrets anywhere except where noted below, and never echo
any value from .env. Do not stop or change my Mac's running app except for the short pauses
described below.

Work through these phases, verifying each before moving on. If something unexpected happens, stop
and tell me instead of improvising anything destructive.

1. Preflight on the Mac
   - Confirm docker compose services are up and note the current git branch and commit
     (`git status`, `git log -1`). If there are uncommitted changes, list them and ask me before
     continuing. The server must run the same commit as the Mac: if that commit is not on
     origin/main, ask me whether to (a) update the Mac to the latest main first (git pull, then
     `docker compose up -d --build`; data is kept) or (b) deploy the Mac's branch/commit as is.
     scripts/deploy_ubuntu.sh and scripts/fns_transfer.sh must exist (they come from PR #4); if
     they don't, stop and tell me to merge PR #4.
   - Record a baseline, saved to a file in a new temporary folder (not in the repo): row counts of
     every table in every non-system schema of the `pms` database (query pg_tables through
     `docker compose exec -T db psql`), the hotels list (id, code, name, alojamiento_id), the
     number of user accounts, and the number of saved conversations in the agent's SQLite file
     (volume agentdata, /data/conversations.sqlite). Also note the docker volume names
     (`docker volume ls`) and which .env keys are set (names only, not values).

2. SSH access
   - Install sshpass if needed (`brew install hudochenkov/sshpass/sshpass`), create a dedicated key
     ~/.ssh/aia_demo_ed25519 if it doesn't exist, and install it on the server once with
     `SSHPASS="$SERVER_PASSWORD" sshpass -e ssh-copy-id -i ~/.ssh/aia_demo_ed25519.pub`.
     From then on use only that key (ssh -i ...). Check the server is Ubuntu 22.04/24.04 and has
     at least 4 GB RAM and 20 GB free disk; report if not.
   - For commands that need root: if SSH_USER is root, run them directly; otherwise pass
     SERVER_PASSWORD to `sudo -S` on standard input (never on the command line).

3. Cloudflare tunnel for aia-demo-cld.goliatt.co
   - With CLOUDFLARE_API_TOKEN: using the Cloudflare API (curl), find the account and the zone id
     of goliatt.co, create a remotely-managed tunnel named "aia-demo-cld" (or reuse it if it
     exists), get its connector token, set its ingress to hostname aia-demo-cld.goliatt.co ->
     service http://web:5050 plus a final http_status:404 rule, and create (or update) a proxied
     CNAME record aia-demo-cld -> <tunnel-id>.cfargotunnel.com. Do not touch any other tunnel or
     DNS record, in particular my Mac's tunnel and aiaclo.goliatt.co.
   - Without the token: tell me exactly what to do in the Cloudflare dashboard (Zero Trust ->
     Networks -> Tunnels -> Create a tunnel -> Cloudflared, name aia-demo-cld; copy the token; the
     Continue button only enables once the connector runs, which phase 4 does; then add the public
     hostname aia-demo-cld.goliatt.co -> HTTP web:5050), and ask me to paste the token into a file
     ~/aia-demo-tunnel-token (mode 600) on the Mac rather than into the chat. Read it from there.

4. Install the app on the server
   - Copy scripts/deploy_ubuntu.sh to the server and run it unattended, as root, with
     `--hostname aia-demo-cld.goliatt.co --no-seed --no-admin` and `--branch` (or a later
     `git checkout <commit>` in /opt/pmsmcprpts) so the server is on exactly the Mac's commit.
     Provide ANTHROPIC_API_KEY (read from my Mac's .env) and CLOUDFLARE_TUNNEL_TOKEN as
     environment variables through a temporary file on the server (mode 600, deleted right after),
     not on a command line. If the repository can't be read, rerun with
     --repo git@github.com:remcaro-rgb/pmsmcprpts.git: the script prints a deploy key; add it with
     the GitHub CLI if `gh` is logged in on the Mac (read-only deploy key on remcaro-rgb/pmsmcprpts),
     otherwise ask me to add it.
   - The script generates new database passwords and secrets on the server. Keep them: never copy
     the Mac's POSTGRES_PASSWORD, PMS_READONLY_PASSWORD, PMS_APP_PASSWORD or PMS_APP_DATABASE_URL.

5. Copy the data (short pauses on the Mac)
   - Database: on the Mac, `docker compose exec -T db pg_dump -U <POSTGRES_USER> -d <POSTGRES_DB>
     -Fc` to a file in the temporary folder (read-only for the Mac, no pause needed).
   - SQLite volumes: stop only the Mac's `agent` and `mcp` services for the few seconds it takes to
     archive the agentdata and mcpdata volumes (and the artifacts volume) with a throwaway
     container (`docker run --rm -v <volume>:/v -v <tmp>:/b alpine tar czf /b/<name>.tgz -C /v .`),
     then start them again and confirm the Mac's site answers on http://localhost:5050.
   - Copy the files to the server (scp with the key) and verify their sha256 sums match.
   - On the server, in /opt/pmsmcprpts: stop mcp, agent, web and fns-sync (leave db running);
     restore the database with `pg_restore --clean --if-exists --single-transaction` into the
     existing pms database as the POSTGRES_USER (the roles pms_readonly and pms_app already exist
     there with the server's passwords); restore each SQLite/artifacts volume archive into the
     matching server volume (project name pmsmcprpts) with a throwaway container, replacing its
     contents.
   - Re-run the database setup scripts that are safe to re-run so roles and grants match the
     server's passwords: `db/init/05_users.sh` and `db/init/06_fns.sql` (check each file's header
     says it is safe to re-run before running it).

6. Settings
   - Merge settings from my Mac's .env into /opt/pmsmcprpts/.env on the server: copy every key that
     is set on the Mac (ANTHROPIC_API_KEY, PMS_CLAUDE_MODEL, WEB_AUTH, WEB_PASSWORD,
     PMS_USER_DIRECTORY, PMS_HOTEL_ACCESS, FNS_*, SMTP_*, PMS_DIGEST_TIME, the OIDC settings and
     anything else), EXCEPT the server-specific ones, which stay as the deploy script set them:
     POSTGRES_*, PMS_READONLY_PASSWORD, PMS_APP_PASSWORD, PMS_APP_DATABASE_URL, WEB_PUBLIC_URL,
     WEB_TRUST_PROXY, CLOUDFLARE_TUNNEL_TOKEN, PMS_PUBLIC_URL, PMS_DOMAIN. Edit the file on the
     server with a script; don't print values. Keep it mode 600.
   - Ask me before turning on, on the server, anything that would then run twice (on the Mac and
     the server): the daily FNS import (fns-sync) and the daily emails (SMTP_* / digest). My
     default answer if I don't say otherwise: run the FNS import on the server too (it only reads
     from FNS), but leave SMTP_HOST empty on the server so people don't get every email twice.

7. Start and verify
   - Run `docker compose up -d --build` on the server (plus `--profile tunnel up -d tunnel`, and
     `--profile fns up -d fns-sync` if the FNS import is on). Wait until healthy.
   - Compare with the Mac baseline: identical row counts in every table of every schema (list any
     differences, e.g. rows the Mac's sync added since the dump), the same hotels, users and number
     of conversations.
   - Check row-level security still works on the server: as pms_readonly without setting
     pms.allowed_hotels, `SELECT count(*) FROM pms.reservations` returns 0.
   - Check https://aia-demo-cld.goliatt.co answers through the tunnel (the sign-in page or the
     password prompt, not a Cloudflare error), the tunnel shows a registered connection in its
     logs, ufw allows only SSH, and no port other than 22 listens on the server's public address
     (`ss -tlnp`).
   - Ask the agent one question on the server (`docker compose exec agent` or curl
     http://127.0.0.1:7001/api/chat on the server, with a user that exists) such as "How did
     occupancy compare across the hotels last quarter?", and confirm the numbers match the same
     question asked on my Mac (http://localhost:7001/api/chat), including the Fragata hotel.

8. Clean up and report
   - Delete the dump and archives from the server and the Mac's temporary folder (keep only the
     baseline file and tell me its path), and the temporary env file on the server.
   - Report: the server's URL, the commit it runs, the baseline-vs-server comparison table, what
     runs on the server (FNS import yes/no, emails yes/no), how to sign in (same accounts and
     passwords as on the Mac), and the commands to update it later
     (`ssh ... 'cd /opt/pmsmcprpts && sudo bash scripts/deploy_ubuntu.sh --hostname
     aia-demo-cld.goliatt.co --no-seed --no-admin'`). Mention anything you could not verify.
```
