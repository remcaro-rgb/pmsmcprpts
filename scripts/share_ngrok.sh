#!/usr/bin/env bash
# Publish the local website (http://localhost:5050) on your free ngrok domain, behind a sign-in.
#
# One-time setup:
#   1. Sign up at https://ngrok.com and install ngrok (brew install ngrok, or ngrok.com/download).
#   2. ngrok config add-authtoken <your token>        (from dashboard.ngrok.com → Your Authtoken)
#   3. Copy your free domain from dashboard.ngrok.com → Domains (e.g. something.ngrok-free.app).
#
# Usage (from the repository folder, with the stack running: docker compose up -d):
#   scripts/share_ngrok.sh --domain something.ngrok-free.app --google you@gmail.com
#   scripts/share_ngrok.sh --domain something.ngrok-free.app --google you@gmail.com,colleague@gmail.com
#   scripts/share_ngrok.sh --domain something.ngrok-free.app --google-domain yourcompany.com
#   scripts/share_ngrok.sh --domain something.ngrok-free.app --password admin:a-long-unique-password
#
# The domain can also come from NGROK_DOMAIN. Press Ctrl+C to stop sharing.
set -euo pipefail

PORT="${PMS_WEB_PORT:-5050}"
DOMAIN="${NGROK_DOMAIN:-}"
EMAILS=""
EMAIL_DOMAINS=""
PASSWORD=""
PUBLIC=0

die() { echo "error: $*" >&2; exit 1; }
usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --google) EMAILS="${2:-}"; shift 2 ;;
    --google-domain) EMAIL_DOMAINS="${2:-}"; shift 2 ;;
    --password) PASSWORD="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --public-no-sign-in) PUBLIC=1; shift ;;  # anyone with the link can spend your Claude credits
    -h|--help) usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 1 ;;
  esac
done

command -v ngrok >/dev/null || die "ngrok is not installed: brew install ngrok (Mac), winget install ngrok.ngrok (Windows) or https://ngrok.com/download"
ngrok config check >/dev/null 2>&1 || die "ngrok is not set up: run 'ngrok config add-authtoken <your token>' (dashboard.ngrok.com → Your Authtoken)"

DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN%/}"
[ -n "$DOMAIN" ] || die "pass --domain with your free domain from dashboard.ngrok.com → Domains (e.g. something.ngrok-free.app)"

# Who may open the site. The website has no sign-in of its own unless WEB_AUTH=oidc is set.
auth_args=()
if [ -n "$EMAILS" ] || [ -n "$EMAIL_DOMAINS" ]; then
  auth_args+=(--oauth google)
  IFS=',' read -ra list <<< "$EMAILS"
  for e in "${list[@]}"; do [ -n "${e// /}" ] && auth_args+=(--oauth-allow-email "${e// /}"); done
  IFS=',' read -ra list <<< "$EMAIL_DOMAINS"
  for d in "${list[@]}"; do [ -n "${d// /}" ] && auth_args+=(--oauth-allow-domain "${d// /}"); done
fi
if [ -n "$PASSWORD" ]; then
  [ -z "$EMAILS$EMAIL_DOMAINS" ] || die "use either --google/--google-domain or --password, not both"
  user="${PASSWORD%%:*}"; pass="${PASSWORD#*:}"
  [[ "$PASSWORD" == *:* && -n "$user" ]] || die "--password must look like user:password"
  [ "${#pass}" -ge 12 ] || die "use a password of at least 12 characters"
  auth_args+=(--basic-auth "$PASSWORD")
fi
if [ ${#auth_args[@]} -eq 0 ] && [ "$PUBLIC" -eq 0 ]; then
  die "add --google you@gmail.com or --password user:long-password, so strangers can't use your Claude credits"
fi

# The site must be running locally.
curl -fsS -o /dev/null --max-time 5 "http://localhost:$PORT/" \
  || die "nothing answers on http://localhost:$PORT; start it first: docker compose up -d"

# Behind ngrok, rate limits should count per visitor (X-Forwarded-For), not per tunnel.
if [ -f .env ] && ! grep -qE '^WEB_TRUST_PROXY=true' .env; then
  echo "Setting WEB_TRUST_PROXY=true in .env and restarting the website…"
  if grep -qE '^WEB_TRUST_PROXY=' .env; then
    sed -i.bak 's/^WEB_TRUST_PROXY=.*/WEB_TRUST_PROXY=true/' .env && rm -f .env.bak
  else
    printf '\nWEB_TRUST_PROXY=true\n' >> .env
  fi
  docker compose up -d web >/dev/null
fi

# Newer ngrok agents take --url; older v3 agents take --domain.
help="$(ngrok http --help 2>&1 || true)"
if [[ "$help" == *"--url"* ]]; then url_arg=(--url "https://$DOMAIN"); else url_arg=(--domain "$DOMAIN"); fi

echo
echo "Sharing http://localhost:$PORT at https://$DOMAIN"
if [ "$PUBLIC" -eq 1 ] && [ ${#auth_args[@]} -eq 0 ]; then
  echo "WARNING: no sign-in. Anyone with the link can use the site and your Claude credits."
elif [ -n "$PASSWORD" ]; then
  echo "Visitors sign in with the user name and password you chose."
else
  echo "Visitors sign in with Google: ${EMAILS:-}${EMAILS:+ }${EMAIL_DOMAINS:+(anyone @${EMAIL_DOMAINS})}"
fi
echo "Free ngrok shows a warning page first; click 'Visit Site'. Press Ctrl+C to stop sharing."
echo
# ${auth_args[@]+...} keeps an empty array working under set -u on macOS's bash 3.2.
exec ngrok http "$PORT" "${url_arg[@]}" ${auth_args[@]+"${auth_args[@]}"}
