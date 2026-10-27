# Prompt: import the rest of 2025 from FNS on the server

Paste the prompt below into **Claude Code running on your Mac**, started in the repository folder
(`cd ~/pmsmcprpts && claude`). It uses the SSH key `~/.ssh/aia_demo_ed25519` that was set up when the
server was cloned. Replace `<SERVER_IP>` and `<SSH_USER>`. If sudo asks for a password, export it
first (`export SERVER_PASSWORD='...'`) so it never appears in the chat.

---

```text
On my server (aia-demo-cld.goliatt.co, IP <SERVER_IP>, SSH user <SSH_USER>, key
~/.ssh/aia_demo_ed25519, app in /opt/pmsmcprpts, run with docker compose), import from the FNSrooms
API the 2025 data that is still missing for the Fragata hotel. Make as few API calls as possible
(date ranges, using the app's `fns_sync history` command) and wait 30 seconds between API calls.
If sudo needs a password, it is in the environment variable SERVER_PASSWORD; pass it to `sudo -S` on
standard input. Never print, log or commit any secret or any value from .env. If anything unexpected
happens, stop and tell me instead of improvising anything destructive.

1. Update the code on the server
   - The `history` command comes from PR #22 (remcaro-rgb/pmsmcprpts). Check that it is merged into
     main (`git log origin/main` locally after `git fetch`). If it isn't, stop and tell me to merge it.
   - On the server, in /opt/pmsmcprpts: `git status` (stop and tell me if there are local changes
     besides .env), `git pull --ff-only`, then rebuild only the importer:
     `docker compose --profile fns build fns-sync`. The website stays up.
   - Check that the command exists: `docker compose --profile fns run --rm fns-sync python -m
     fns_sync history --help`.

2. Baseline
   - Save a baseline to a new temporary folder on the Mac (not in the repo): `python -m fns_sync
     status` and the row count per month of 2025 for each pms.fns_* table that has a date column
     (business date, stay or creation date), plus `SELECT step, history_from FROM pms.fns_sync_steps`
     for the FNS hotel. Run the queries with `docker compose exec -T db psql -U <POSTGRES_USER> -d
     <POSTGRES_DB>` (read the user and db names from the server's .env without printing anything else).
   - The earliest `history_from` is where the loaded history starts. If it is already on or before
     2025-01-01, tell me there is nothing to import and stop.

3. Plan
   - Stop the daily import so it doesn't run at the same time: `docker compose --profile fns stop
     fns-sync`.
   - Run `docker compose --profile fns run --rm fns-sync python -m fns_sync history --from
     2025-01-01 --pause 30 --plan`. It makes no API calls. `--to` defaults to the day before the
     loaded history. Show me the calls per step, the total and the estimated time, and continue.

4. Import
   - Run the same command without `--plan`, in the background on the server so a dropped SSH
     connection doesn't stop it: `nohup docker compose --profile fns run --rm -T fns-sync python -m
     fns_sync history --from 2025-01-01 --pause 30 > ~/fns-history-2025.log 2>&1 &`.
   - Watch the log every few minutes (tail, not the whole file) until it finishes, and tell me the
     progress. Don't start a second run while one is running.
   - If it ends with failed steps, show me which steps and errors from the log or `fns_sync status`
     (no guest data). Re-run only those steps once with `--only <steps>`, same `--from`, `--pause 30`
     (and the same `--to` the plan showed). If they fail again, stop and tell me.

5. Verify and restart
   - Repeat the baseline queries and show a before/after table by month for 2025: every month from
     January up to the start of the old history should now have rows (revenue: one row per day). Also
     show `history_from` for each step, which should now be 2025-01-01.
   - Start the daily import again: `docker compose --profile fns start fns-sync`. Check its logs show
     no errors and that the website still answers (https://aia-demo-cld.goliatt.co).
   - Ask the agent one question about Fragata early in 2025, such as "What was Fragata's occupancy and
     revenue in March 2025?" (curl http://127.0.0.1:7001/api/chat on the server with a user that can
     see Fragata), and check the numbers against SQL.

6. Report: the number of API calls made, the time taken, the before/after table, any steps that
   failed, and the path of the log. Delete the temporary folder on the Mac except the baseline file.
```
