#!/usr/bin/env bash
# Active bookings of the active FNS hotels (Admin page, FNS import), straight from the FNS API, as a
# CSV on this computer: hotel, name, booking number, check-in date and email.
#
#   scripts/fns_active_bookings.sh usuario@servidor                 # every active hotel
#   scripts/fns_active_bookings.sh usuario@servidor --hotel FRA     # one hotel
#   scripts/fns_active_bookings.sh usuario@servidor --created-days 730
#
# FNS finds bookings by the day they were made (30 days per call), so it looks at those made in the
# last --created-days (365) and keeps the ones whose stay hasn't ended. PMS_DIR sets where the
# installation is on the server (default /opt/pmsmcprpts). The file has guests' emails: keep it
# private.
set -euo pipefail
HOST="${1:?Uso: $0 usuario@servidor [--hotel CODIGO] [--created-days N]}"
shift
DIR="${PMS_DIR:-/opt/pmsmcprpts}"
OUT="reservas_activas_$(date +%Y%m%d).csv"
ARGS=""
for a in "$@"; do ARGS+=" $(printf '%q' "$a")"; done

umask 077  # only you can read the file
if ${SSH:-ssh} "$HOST" "cd $(printf '%q' "$DIR") && sudo docker compose --profile fns run --rm -T fns-sync python -m fns_sync bookings$ARGS" > "$OUT.part"; then
  status=0
else
  status=$?  # 1: some hotel couldn't be read (said above); the others are in the file
fi
if [ -s "$OUT.part" ]; then
  mv "$OUT.part" "$OUT"
  echo "$(($(wc -l < "$OUT") - 1)) reservas activas en $OUT"
else
  rm -f "$OUT.part"
  echo "No se generó el archivo (revisa los mensajes de arriba)." >&2
fi
exit "$status"
