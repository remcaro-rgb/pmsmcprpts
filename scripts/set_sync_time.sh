#!/usr/bin/env bash
# Change when the nightly FNS import runs (FNS_SYNC_TIME, hotel time) and restart fns-sync to use it.
#
# Usage (from the repository folder):
#   scripts/set_sync_time.sh            # 03:30
#   scripts/set_sync_time.sh 04:15
#
# Restarting doesn't import again if today's import already ran; it only moves the next one.
set -euo pipefail

TIME="${1:-03:30}"
ENV_FILE=".env"

die() { echo "error: $*" >&2; exit 1; }

[[ "$TIME" =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9]$ ]] || die "the time must look like 03:30 (it is '$TIME')"
[ -f "$ENV_FILE" ] || die "no $ENV_FILE here: run this from the repository folder"

if grep -q '^FNS_SYNC_TIME=' "$ENV_FILE"; then
  tmp="$(mktemp)"
  sed "s/^FNS_SYNC_TIME=.*/FNS_SYNC_TIME=$TIME/" "$ENV_FILE" > "$tmp" && cat "$tmp" > "$ENV_FILE" && rm -f "$tmp"
else
  printf '\nFNS_SYNC_TIME=%s\n' "$TIME" >> "$ENV_FILE"
fi
echo "FNS_SYNC_TIME=$TIME in $ENV_FILE"

# Recreate the service so it reads the new value (a plain restart keeps the old environment).
docker compose --profile fns up -d fns-sync
sleep 5
docker compose logs --tail 20 fns-sync | grep "next import at" | tail -1 || true
