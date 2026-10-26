#!/usr/bin/env bash
# Share the website through a Cloudflare Tunnel (cloudflared runs as a Docker service; outbound
# connections only, nothing opened on your router or firewall).
#
#   scripts/share_cloudflare.sh --password admin:a-long-unique-password
#       Quick tunnel: no Cloudflare account or domain needed. Prints a random
#       https://….trycloudflare.com address (a new one each time). Visitors type that user name and
#       password. The password is saved to .env (WEB_PASSWORD), so later runs need no options.
#       With user accounts on (WEB_AUTH=password in .env) no --password is needed: visitors sign in
#       with their accounts.
#
#   scripts/share_cloudflare.sh --named
#       Named tunnel on your own domain, with CLOUDFLARE_TUNNEL_TOKEN in .env (see README). Protect it
#       with user accounts (WEB_AUTH=password), WEB_AUTH=oidc, WEB_PASSWORD, or a Cloudflare Access
#       policy (then add --access).
#       With PMS_PUBLIC_URL set (e.g. https://mcp.yourdomain.com), it also checks the MCP server's
#       sign-in settings and that the connector address answers, for ChatGPT, Claude and other
#       apps. Add --mcp-only when the tunnel has no public hostname for the website.
#
#   scripts/share_cloudflare.sh --stop
#
# Run from the repository folder after `docker compose up -d` (and the seed step) has worked.
set -euo pipefail

MODE=quick
PASSWORD=""
ACCESS=0
MCP_ONLY=0

die() { echo "error: $*" >&2; exit 1; }
usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --password) PASSWORD="${2:-}"; shift 2 ;;
    --named) MODE=named; shift ;;
    --access) ACCESS=1; shift ;;  # a Cloudflare Access policy protects the named tunnel's hostname
    --mcp-only) MCP_ONLY=1; shift ;;  # the named tunnel publishes only the MCP server
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
web_auth="$(env_get WEB_AUTH | tr '[:upper:]' '[:lower:]')"

if [ "$MODE" = quick ]; then
  # A quick tunnel's address changes every time, so the OIDC sign-in can't be used with it.
  # User accounts (WEB_AUTH=password) work with any address.
  [ -n "$web_password" ] || [ "$web_auth" = password ] || die "a quick tunnel needs sign-in so strangers can't spend your Claude credits:
  turn on user accounts (WEB_AUTH=password, see README) or: scripts/share_cloudflare.sh --password admin:a-long-unique-password"
else
  [ -n "$(env_get CLOUDFLARE_TUNNEL_TOKEN)" ] || die "set CLOUDFLARE_TUNNEL_TOKEN in .env (Zero Trust → Networks → Tunnels → your tunnel → token)"
  if [ "$MCP_ONLY" -eq 0 ] && [ -z "$web_password" ] && [ "$web_auth" != oidc ] && [ "$web_auth" != password ] \
     && [ "$ACCESS" -eq 0 ]; then
    die "protect the site: user accounts (WEB_AUTH=password) or WEB_AUTH=oidc in .env, --password user:long-password, or a Cloudflare Access policy on the hostname (then add --access)"
  fi
fi

# The MCP server for ChatGPT, Claude and other apps: public only with its own sign-in.
mcp_url="$(env_get PMS_PUBLIC_URL)"; mcp_url="${mcp_url%/}"
if [ "$MCP_ONLY" -eq 1 ] && [ -z "$mcp_url" ]; then
  die "--mcp-only needs PMS_PUBLIC_URL in .env (e.g. https://mcp.yourdomain.com)"
fi
if [ -n "$mcp_url" ]; then
  [ "$MODE" = named ] || die "PMS_PUBLIC_URL is set, but a quick tunnel only shares the website and its address changes on every start; use --named"
  [[ "$mcp_url" == https://* ]] || die "PMS_PUBLIC_URL must start with https:// (e.g. https://mcp.yourdomain.com)"
  [[ "$mcp_url" != *trycloudflare.com* ]] || die "PMS_PUBLIC_URL can't be a quick-tunnel address; use your named tunnel's hostname"
  missing=""
  for k in PMS_OIDC_ISSUER PMS_OIDC_CLIENT_ID PMS_OIDC_CLIENT_SECRET PMS_MCP_SERVICE_TOKEN; do
    [ -n "$(env_get "$k")" ] || missing="$missing $k"
  done
  [ -z "$missing" ] || die "the MCP connector needs these in .env:$missing (see README: Connect from ChatGPT, Claude and other apps)"
  if [ -z "$(env_get PMS_ALLOWED_EMAILS)$(env_get PMS_ALLOWED_DOMAINS)" ] && [ "$(env_get PMS_ALLOW_ANY_USER)" != true ]; then
    die "set PMS_ALLOWED_EMAILS and/or PMS_ALLOWED_DOMAINS in .env: who may connect to the MCP server"
  fi
  token="$(env_get PMS_MCP_SERVICE_TOKEN)"
  [ "${#token}" -ge 32 ] || die "PMS_MCP_SERVICE_TOKEN must be at least 32 characters: openssl rand -hex 32"
fi

# Behind the tunnel, rate limits should count per visitor (X-Forwarded-For), not per tunnel.
[ "$(env_get WEB_TRUST_PROXY)" = true ] || env_set WEB_TRUST_PROXY true

echo "Starting the site (the website restarts if its settings changed)…"
docker compose up -d >/dev/null

if [ "$MODE" = named ]; then
  compose stop quicktunnel >/dev/null 2>&1 || true
  compose up -d tunnel >/dev/null
  echo
  [ "$MCP_ONLY" -eq 1 ] || echo "Website shared on the public hostname you set for it in the Cloudflare dashboard."
  if [ -n "$mcp_url" ]; then
    # The sign-in metadata ChatGPT and Claude read first; it names the issuer they'll trust.
    printf "Checking the MCP server at %s" "$mcp_url"
    meta=""
    for _ in $(seq 1 30); do
      meta="$(curl -fsS --max-time 5 "$mcp_url/.well-known/oauth-authorization-server" 2>/dev/null || true)"
      [ -n "$meta" ] && break
      printf "."; sleep 2
    done
    echo
    if [[ "$meta" == *"\"issuer\""* ]]; then
      echo "MCP connector address: $mcp_url/mcp"
      echo "  ChatGPT: Settings → Connectors (Developer Mode) → create a connector with that URL, OAuth."
      echo "  Claude:  Settings → Connectors → Add custom connector with that URL."
    else
      echo "WARNING: $mcp_url/.well-known/oauth-authorization-server doesn't answer yet."
      echo "  Check the tunnel has a public hostname for it pointing to http://mcp:7070, that"
      echo "  PMS_PUBLIC_URL matches that hostname, and: docker compose logs mcp"
    fi
  fi
  echo "Tunnel logs: docker compose --profile tunnel logs -f tunnel"
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
if [ -n "$web_password" ]; then
  echo "Visitors first type the user name and password in WEB_PASSWORD (user: ${web_password%%:*})."
fi
[ "$web_auth" = password ] && echo "Visitors sign in with their user accounts."
echo "The address changes each time the tunnel restarts. Stop sharing: scripts/share_cloudflare.sh --stop"
