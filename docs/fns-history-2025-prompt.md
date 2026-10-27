# Prompt: import the rest of 2025 from FNS on the server

Paste the prompt below into **Claude Code running on your Mac**, started in the repository folder
(`cd ~/pmsmcprpts && claude`). It uses the SSH key `~/.ssh/aia_demo_ed25519` that was set up when the
server was cloned. Replace `<SERVER_IP>` and `<SSH_USER>`. If sudo asks for a password, export it
first (`export SERVER_PASSWORD='...'`) so it never appears in the chat.

---

```text
On my server (aia-demo-cld.goliatt.co, IP <SERVER_IP>, SSH user <SSH_USER>, key
~/.ssh/aia_demo_ed25519, app in /opt/pmsmcprpts, run with docker compose), import from the FNSrooms
API the 2025 data that is still missing for the Fragata hotel, one calendar month per API call:
each call asks for a whole month (January to September 2025, and October 2025 from the 1st up to
the day before the history already loaded), using the app's `fns_sync history` command once per
month. Wait 30 seconds between API calls.
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

3. Plan the months
   - Stop the daily import so it doesn't run at the same time: `docker compose --profile fns stop
     fns-sync`.
   - Let H be the earliest `history_from` from the baseline (expected in October 2025). The months
     to load, newest first: the month of H, from its 1st to H minus one day (skip it if H is the 1st),
     then each earlier month down to January 2025, from its 1st to its last day.
     Go newest first on purpose: each finished month moves `history_from` back, so if the import
     stops halfway the loaded history stays one unbroken range and you can continue from there.
   - For each month run `docker compose --profile fns run --rm fns-sync python -m fns_sync history
     --from <first day> --to <last day> --pause 30 --plan` (no API calls) and show me a table:
     month, calls per step, total, estimated minutes, plus the grand total. Expect one call per
     method for the month (revenue, production_cc, sales_reservations, pos, production; accounting
     3, one per report). The API allows at most 30 days per reservation and exchange-rate search, so
     in 31-day months those are read as days 1-30 plus day 31 (one extra call per reservation state
     and per currency); tell me that number too. Then continue.

4. Import, one month at a time
   - Write a small script on the server (~/fns-history-2025.sh) that runs, for each month in the
     order above, `docker compose --profile fns run --rm -T fns-sync python -m fns_sync history
     --from <first day> --to <last day> --pause 30`, appends its output to ~/fns-history-2025.log
     with a header line per month, and stops at the first month that exits with an error. The command
     already waits 30 seconds after every API call, the last one included, so consecutive months stay
     at least 30 seconds apart. Show me the script, then start it in the background so a dropped SSH
     connection doesn't stop it: `nohup bash ~/fns-history-2025.sh >/dev/null 2>&1 &`.
   - Check the log every few minutes (tail, not the whole file) and tell me which month it is on.
     Don't start a second run while one is running.
   - If a month ends with failed steps, show me the steps and errors (from the log or `fns_sync
     status`; no guest data). Re-run only those steps for that month once with `--only <steps>`, the
     same `--from`/`--to` and `--pause 30`, then continue with the remaining months. If they fail again,
     stop and tell me.

5. Verify and restart
   - Repeat the baseline queries and show a before/after table by month for 2025: every month from
     January up to the start of the old history should now have rows (revenue: one row per day). Also
     show `history_from` for each step, which should now be 2025-01-01.
   - Start the daily import again: `docker compose --profile fns start fns-sync`. Check its logs show
     no errors and that the website still answers (https://aia-demo-cld.goliatt.co).
   - Ask the agent one question about Fragata early in 2025, such as "What was Fragata's occupancy and
     revenue in March 2025?" (curl http://127.0.0.1:7001/api/chat on the server with a user that can
     see Fragata), and check the numbers against SQL.

6. Report: the number of API calls made per month and in total, the time taken, the before/after table, any steps that
   failed, and the path of the log. Delete the temporary folder on the Mac except the baseline file.
```
