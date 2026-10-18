#!/usr/bin/env bash
# Share the website through a Cloudflare Tunnel (cloudflared runs as a Docker service; outbound
# connections only, nothing opened on your router or firewall).
#
#   scripts/share_cloudflare.sh --password admin:a-long-unique-password
#       Quick tunnel: no Cloudflare account or domain needed. Prints a random
#       https://….trycloudflare.com address (a new one each time). Visitors type that user name and
#       password. The password is saved to .env (WEB_PASSWORD), so later runs need no options.
#
#   scripts/share_cloudflare.sh --named
#       Named tunnel on your own domain, with CLOUDFLARE_TUNNEL_TOKEN in .env (see README). Protect it
#       with WEB_PASSWORD, WEB_AUTH=oidc, or a Cloudflare Access policy (then add --access).
#
#   scripts/share_cloudflare.sh --stop
#
# Run from the repository folder after `docker compose up -d` (and the seed step) has worked.
set -euo pipefail

MODE=quick
PASSWORD=""
ACCESS=0

die() { echo "error: $*" >&2; exit 1; }
usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --password) PASSWORD="${2:-}"; shift 2 ;;
    --named) MODE=named; shift ;;
    --access) ACCESS=1; shift ;;  # a Cloudflare Access policy protects the named tunnel's hostname
    --stop) MODE=stop; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 1 ;;
  esac
done

[ -f docker-compose.yml ] || die "run this from the pmsmcprpts folder"
command -v docker >/dev/null || die "Docker is not installed or not on PATH"
[ -f .env ] || die "no .env file; create it first: cp .env.example .env (and set ANTHROPIC_API_KEY)"

compose() { docker compose --profile quicktunnel --profile tunnel "$@"; }

if [ "$MODE" = stop ]; then
  compose stop quicktunnel tunnel >/dev/null 2>&1 || true
  echo "Stopped sharing. The site still runs locally at http://localhost:${PMS_WEB_PORT:-5050}"
  exit 0
fi

env_get() {  # last value of KEY in .env, without surrounding quotes
  local v
  v="$(grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- || true)"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}
env_set() {  # set KEY=VALUE in .env (replacing an existing line), without sed escaping problems
  local tmp
  tmp="$(mktemp)"
  K="$1" V="$2" awk 'BEGIN { k = ENVIRON["K"]; v = ENVIRON["V"]; done = 0 }
    index($0, k "=") == 1 { if (!done) { print k "=" v; done = 1 }; next }
    { print }
    END { if (!done) print k "=" v }' .env > "$tmp"
  cat "$tmp" > .env && rm -f "$tmp"
}

if [ -n "$PASSWORD" ]; then
  user="${PASSWORD%%:*}"; pass="${PASSWORD#*:}"
  [[ "$PASSWORD" == *:* && -n "$user" ]] || die "--password must look like user:password"
  [ "${#pass}" -ge 12 ] || die "use a password of at least 12 characters"
  # .env values are read by Docker Compose, which expands $ and treats quotes, # and spaces specially.
  case "$PASSWORD" in *[\$\'\"\\#\ ]*) die "leave out these characters, which .env treats specially: \$ ' \" \\ # and spaces" ;; esac
  env_set WEB_PASSWORD "$PASSWORD"
fi
web_password="$(env_get WEB_PASSWORD)"
web_auth="$(env_get WEB_AUTH)"

if [ "$MODE" = quick ]; then
  # A quick tunnel's address changes every time, so the OIDC sign-in can't be used with it.
  [ -n "$web_password" ] || die "a quick tunnel needs a password so strangers can't spend your Claude credits:
  scripts/share_cloudflare.sh --password admin:a-long-unique-password"
else
  [ -n "$(env_get CLOUDFLARE_TUNNEL_TOKEN)" ] || die "set CLOUDFLARE_TUNNEL_TOKEN in .env (Zero Trust → Networks → Tunnels → your tunnel → token)"
  if [ -z "$web_password" ] && [ "$web_auth" != oidc ] && [ "$ACCESS" -eq 0 ]; then
    die "protect the site: --password user:long-password, WEB_AUTH=oidc in .env, or a Cloudflare Access policy on the hostname (then add --access)"
  fi
fi

# Behind the tunnel, rate limits should count per visitor (X-Forwarded-For), not per tunnel.
[ "$(env_get WEB_TRUST_PROXY)" = true ] || env_set WEB_TRUST_PROXY true

echo "Starting the site (the website restarts if its settings changed)…"
docker compose up -d >/dev/null

if [ "$MODE" = named ]; then
  compose stop quicktunnel >/dev/null 2>&1 || true
  compose up -d tunnel >/dev/null
  echo
  echo "Shared on the public hostname you set for this tunnel in the Cloudflare dashboard."
  echo "Check the connection: docker compose --profile tunnel logs -f tunnel"
  echo "Stop sharing: scripts/share_cloudflare.sh --stop"
  exit 0
fi

compose stop tunnel >/dev/null 2>&1 || true
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
compose up -d --force-recreate quicktunnel >/dev/null
printf "Waiting for the tunnel address"
url=""
for _ in $(seq 1 45); do
  url="$(compose logs --since "$since" quicktunnel 2>/dev/null \
    | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -n 1 || true)"
  [ -n "$url" ] && break
  printf "."; sleep 2
done
echo
[ -n "$url" ] || die "no address yet; see: docker compose --profile quicktunnel logs quicktunnel"

echo
echo "Shared at: $url"
echo "Visitors sign in with the user name and password in WEB_PASSWORD (user: ${web_password%%:*})."
echo "The address changes each time the tunnel restarts. Stop sharing: scripts/share_cloudflare.sh --stop"
