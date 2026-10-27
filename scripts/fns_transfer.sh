#!/usr/bin/env bash
# Copy the FNSrooms data (the FNS hotels and every pms.fns_* table) from one installation to another,
# e.g. from your computer to a server, without calling the FNS API again.
#
#   On the source (your computer), in the repository folder:
#     scripts/fns_transfer.sh export                 # writes fns-export-<date>.tar.gz
#   Copy it to the server, e.g.: scp fns-export-*.tar.gz you@server:/opt/pmsmcprpts/
#   On the target (the server), in the repository folder:
#     scripts/fns_transfer.sh import fns-export-<date>.tar.gz
#
# Import runs in one transaction. Each FNS hotel is matched by its FNS alojamiento_id: an existing
# hotel keeps its id, a missing one is created, and every row is moved to the target's hotel id. That
# hotel's FNS rows are replaced by the exported ones; exchange rates are merged. The sync history
# (fns_sync_steps) comes along, so the target's daily sync continues where the source stopped instead
# of downloading the whole history again. Row counts are checked against the export before
# committing. Other hotels, the sample data and the user accounts are not touched: after importing,
# give people the new hotel under Admin.
#
# Both installations must run the same version of the app (the same fns_* columns). Uses the db
# service of docker compose; set PSQL to another command (e.g. "psql -d pms") to skip Docker.
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

# Tables that reference another fns_* table are filled after their parents.
CHILDREN="fns_accounting_lines fns_reservation_rooms fns_sales_reservation_days"
# The FNS hotels: every hotel the FNS import has written data for.
FNS_HOTELS="SELECT hotel_id FROM pms.fns_sync_steps UNION SELECT hotel_id FROM pms.fns_revenue_daily
            UNION SELECT hotel_id FROM pms.fns_reservations UNION SELECT hotel_id FROM pms.fns_master_items"

env_get() { [ -f .env ] && grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | tr -d "\"'" || true; }
db_user="$(env_get POSTGRES_USER)"; db_user="${db_user:-pms}"
db_name="$(env_get POSTGRES_DB)"; db_name="${db_name:-pms}"
if [ -n "${PSQL:-}" ]; then
  psql_() { $PSQL -X -q -v ON_ERROR_STOP=1 "$@"; }
else
  [ -f docker-compose.yml ] || die "run this from the repository folder (or set PSQL)"
  DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"
  psql_() { $DOCKER compose exec -T db psql -X -q -v ON_ERROR_STOP=1 -U "$db_user" -d "$db_name" "$@"; }
fi

fns_tables() {
  psql_ -At -c "SELECT tablename FROM pg_tables WHERE schemaname = 'pms' AND tablename LIKE 'fns\_%' ORDER BY 1"
}

do_export() {
  local out="${1:-fns-export-$(date +%Y%m%d-%H%M).tar.gz}"
  local hotels; hotels="$(psql_ -At -c "SELECT count(*) FROM pms.hotels WHERE id IN ($FNS_HOTELS)")"
  [ "$hotels" -gt 0 ] || die "no FNS data in this database"
  echo "Exporting $hotels FNS hotel(s):"
  psql_ -c "COPY (SELECT * FROM pms.hotels WHERE id IN ($FNS_HOTELS) ORDER BY id) TO STDOUT WITH (FORMAT csv, HEADER true)" \
    > "$WORK/hotels.csv"
  echo "hotels $(($(wc -l < "$WORK/hotels.csv") - 1))" > "$WORK/manifest"
  local t n
  for t in $(fns_tables); do
    psql_ -c "COPY pms.$t TO STDOUT WITH (FORMAT csv, HEADER true)" > "$WORK/$t.csv"
    n="$(psql_ -At -c "SELECT count(*) FROM pms.$t")"
    echo "$t $n" >> "$WORK/manifest"
    printf '  %-28s %10s rows\n' "$t" "$n"
  done
  tar -czf "$out" -C "$WORK" .
  echo "Wrote $out ($(du -h "$out" | cut -f1))."
}

do_import() {
  local file="${1:?usage: scripts/fns_transfer.sh import <file.tar.gz>}"
  [ -f "$file" ] || die "no such file: $file"
  tar -xzf "$file" -C "$WORK"
  [ -f "$WORK/manifest" ] && [ -f "$WORK/hotels.csv" ] || die "$file is not an export from this script"

  local target_tables; target_tables=" $(fns_tables | tr '\n' ' ') "
  local t
  for t in $(awk '$1 != "hotels" {print $1}' "$WORK/manifest"); do
    [[ "$target_tables" == *" $t "* ]] || die "this database has no pms.$t; update the app here first (deploy script or git pull + docker compose up -d --build)"
  done

  # The daily sync must not write while the import replaces the same rows.
  local sync_was_running=0
  if [ -z "${PSQL:-}" ] && $DOCKER compose --profile fns ps --status running --services 2>/dev/null | grep -qx fns-sync; then
    sync_was_running=1
    echo "Pausing the FNS daily sync during the import..."
    $DOCKER compose --profile fns stop fns-sync >/dev/null
  fi

  local sql="$WORK/import.sql"
  {
    echo "BEGIN;"
    echo "SET client_min_messages = warning;"
    echo "CREATE TEMP TABLE imp_hotels (LIKE pms.hotels);"
    copy_block hotels imp_hotels "$WORK/hotels.csv"
    cat <<'SQL'
CREATE TEMP TABLE hotel_map (old_id integer PRIMARY KEY, new_id integer NOT NULL);
-- Hotels that already exist here (same FNS alojamiento_id) keep their id and settings.
INSERT INTO hotel_map SELECT i.id, h.id FROM imp_hotels i JOIN pms.hotels h ON h.alojamiento_id = i.alojamiento_id;
-- The others are created with a new id.
WITH ins AS (
  INSERT INTO pms.hotels (code, name, city, country, star_rating, total_rooms, currency, timezone, opened_on,
                          alojamiento_id, pms_id)
  SELECT code, name, city, country, star_rating, total_rooms, currency, timezone, opened_on, alojamiento_id, pms_id
  FROM imp_hotels i WHERE NOT EXISTS (SELECT 1 FROM hotel_map m WHERE m.old_id = i.id)
  RETURNING id, alojamiento_id)
INSERT INTO hotel_map SELECT i.id, ins.id FROM ins JOIN imp_hotels i ON i.alojamiento_id = ins.alojamiento_id;
DO $$ BEGIN
  IF (SELECT count(*) FROM hotel_map) <> (SELECT count(*) FROM imp_hotels) THEN
    RAISE EXCEPTION 'every exported hotel needs an FNS alojamiento_id to be matched';
  END IF;
END $$;
SQL
    local parents=() children=() name
    for name in $(awk '$1 != "hotels" {print $1}' "$WORK/manifest"); do
      if [[ " $CHILDREN " == *" $name "* ]]; then children+=("$name"); else parents+=("$name"); fi
    done
    # Remove these hotels' current FNS rows (children first), then load the exported ones.
    for name in "${children[@]}" "${parents[@]}"; do
      [ "$name" = fns_exchange_rates ] && continue
      echo "DELETE FROM pms.$name WHERE hotel_id IN (SELECT new_id FROM hotel_map);"
    done
    for name in "${parents[@]}" "${children[@]}"; do
      load_table "$name" "$WORK/$name.csv"
    done
    echo "SELECT 'hotel ' || i.code || ' (' || i.name || '): id ' || m.old_id || ' there -> id ' || m.new_id || ' here'
          FROM hotel_map m JOIN imp_hotels i ON i.id = m.old_id ORDER BY m.new_id;"
    echo "COMMIT;"
  } > "$sql"

  echo "Importing (one transaction; nothing changes if any step fails)..."
  local status=0
  psql_ -At < "$sql" || status=$?
  if [ "$sync_was_running" -eq 1 ]; then $DOCKER compose --profile fns start fns-sync >/dev/null; fi
  [ "$status" -eq 0 ] || die "import failed; the database is unchanged"
  psql_ -c "ANALYZE" >/dev/null
  echo "Done. Rows now in this database for the imported hotels:"
  for name in $(awk '$1 != "hotels" {print $1}' "$WORK/manifest"); do
    printf '  %-28s %10s rows\n' "$name" "$(psql_ -At -c "SELECT count(*) FROM pms.$name")"
  done
  echo "Next: in the website's Admin page, give people access to the imported hotel(s)."
}

copy_block() {  # copy_block <name> <table> <csv>: a COPY ... FROM STDIN block with the file's rows
  local cols; cols="$(head -n 1 "$3")"
  echo "COPY $2 ($cols) FROM STDIN WITH (FORMAT csv, HEADER true);"
  cat "$3"
  echo '\.'
}

load_table() {  # load_table <table> <csv>
  local t="$1" csv="$2" cols insert_cols expected
  cols="$(head -n 1 "$csv")"
  expected="$(awk -v t="$t" '$1 == t {print $2}' "$WORK/manifest")"
  insert_cols="$cols"
  [ "$t" = fns_sync_runs ] && insert_cols="$(echo "$cols" | tr ',' '\n' | grep -vx id | paste -sd, -)"  # new ids here
  echo "CREATE TEMP TABLE imp_$t (LIKE pms.$t);"
  copy_block "$t" "imp_$t" "$csv"
  if [ "$t" = fns_exchange_rates ]; then
    echo "INSERT INTO pms.$t ($cols) SELECT $cols FROM imp_$t
          ON CONFLICT (rate_date, from_moneda_id, to_moneda_id) DO UPDATE SET rate = EXCLUDED.rate;"
  else
    echo "UPDATE imp_$t x SET hotel_id = m.new_id FROM hotel_map m WHERE x.hotel_id = m.old_id;"
    echo "INSERT INTO pms.$t ($insert_cols) SELECT $insert_cols FROM imp_$t;"
  fi
  # Stop (and roll back) if any row didn't arrive.
  echo "DO \$\$ BEGIN IF (SELECT count(*) FROM imp_$t) <> $expected THEN
          RAISE EXCEPTION '$t: expected $expected rows, read %', (SELECT count(*) FROM imp_$t); END IF; END \$\$;"
}

case "${1:-}" in
  export) shift; do_export "$@" ;;
  import) shift; do_import "$@" ;;
  -h|--help|"") usage 0 ;;
  *) echo "unknown command: $1" >&2; usage 1 ;;
esac
