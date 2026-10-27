#!/usr/bin/env bash
# Install the whole app on an Ubuntu server (22.04 or 24.04) and publish it through a Cloudflare
# named tunnel: Docker, the code, a .env with fresh secrets, the database and its sample data, the
# MCP server, agent and website, the tunnel, a firewall that only allows SSH, and the first
# administrator. Nothing is opened to the internet except SSH; the tunnel connects outwards.
#
#   bash deploy_ubuntu.sh --hostname aia-demo-cld.goliatt.co
#
# Options:
#   --hostname NAME      public address the tunnel serves (sets WEB_PUBLIC_URL). Required.
#   --repo URL           git repository (default: https://github.com/remcaro-rgb/pmsmcprpts.git).
#                        For a private repository use git@github.com:remcaro-rgb/pmsmcprpts.git;
#                        the script then creates a read-only deploy key and tells you where to add it.
#   --branch NAME        branch to run (default: main)
#   --dir PATH           where to put the code (default: /opt/pmsmcprpts)
#   --admin-email EMAIL  first administrator (asked for on a new install if not given)
#   --admin-name NAME
#   --no-seed            skip the sample data (e.g. when you restore a database copy afterwards)
#   --no-admin           don't create an administrator (e.g. the restored copy has its accounts)
#
# Secrets are read from the environment if set (ANTHROPIC_API_KEY, CLOUDFLARE_TUNNEL_TOKEN) or asked
# for without echoing; they go only into <dir>/.env (mode 600). Safe to run again to update: it pulls
# the branch, keeps the existing .env and data, and rebuilds.
set -euo pipefail

# Everything runs inside main(), so bash has read the whole file before `git pull` can change it.
main() {
HOSTNAME_=""
REPO="https://github.com/remcaro-rgb/pmsmcprpts.git"
BRANCH="main"
DIR="/opt/pmsmcprpts"
ADMIN_EMAIL=""
ADMIN_NAME=""
SEED=1
ADMIN=1

die() { echo "error: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }
usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --hostname) HOSTNAME_="${2:-}"; shift 2 ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    --dir) DIR="${2:-}"; shift 2 ;;
    --admin-email) ADMIN_EMAIL="${2:-}"; shift 2 ;;
    --admin-name) ADMIN_NAME="${2:-}"; shift 2 ;;
    --no-seed) SEED=0; shift ;;
    --no-admin) ADMIN=0; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 1 ;;
  esac
done
[ -n "$HOSTNAME_" ] || die "pass --hostname, e.g. --hostname aia-demo-cld.goliatt.co"
[[ "$HOSTNAME_" =~ ^[a-z0-9.-]+$ ]] || die "--hostname must be a plain host name, without https:// or a path"

. /etc/os-release 2>/dev/null || true
[ "${ID:-}" = ubuntu ] || die "this script is for Ubuntu (found: ${PRETTY_NAME:-unknown})"
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; $SUDO -v || die "needs sudo rights"; fi
DOCKER="$SUDO docker"

# --- 1. System packages, Docker and the firewall -------------------------------------------------
step "Installing system packages"
$SUDO apt-get update -qq
$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates curl git openssl python3 ufw >/dev/null

if ! $DOCKER compose version >/dev/null 2>&1; then
  step "Installing Docker Engine (official repository)"
  $SUDO install -m 0755 -d /etc/apt/keyrings
  $SUDO curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  $SUDO chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
  $SUDO apt-get update -qq
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin >/dev/null
fi
$SUDO systemctl enable --now docker >/dev/null

step "Firewall: allow SSH only (the tunnel needs no open ports)"
$SUDO ufw allow OpenSSH >/dev/null
$SUDO ufw --force enable >/dev/null
$SUDO ufw status | head -5

# --- 2. The code ---------------------------------------------------------------------------------
step "Getting the code into $DIR ($BRANCH)"
KEY="$HOME/.ssh/pmsmcprpts_deploy"
if [[ "$REPO" == git@* ]]; then
  if [ ! -f "$KEY" ]; then
    mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
    ssh-keygen -q -t ed25519 -N "" -C "pmsmcprpts deploy $(hostname)" -f "$KEY"
  fi
  export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
fi
if ! git ls-remote --heads "$REPO" "$BRANCH" >/dev/null 2>&1; then
  if [[ "$REPO" == git@* ]]; then
    echo "GitHub refused this server's deploy key. Add it as a read-only deploy key:" >&2
    echo "  https://github.com/remcaro-rgb/pmsmcprpts/settings/keys -> Add deploy key, paste:" >&2
    echo >&2; cat "$KEY.pub" >&2; echo >&2
    die "then run this script again"
  fi
  die "can't read $REPO. If the repository is private, run again with --repo git@github.com:remcaro-rgb/pmsmcprpts.git"
fi
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH"
  git -C "$DIR" checkout -q "$BRANCH"
  git -C "$DIR" merge -q --ff-only "origin/$BRANCH" || die "$DIR has local changes; resolve them, then run again"
else
  $SUDO mkdir -p "$DIR" && $SUDO chown "$(id -u):$(id -g)" "$DIR"
  git clone -q --branch "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"
echo "At commit $(git log --oneline -1)"

# --- 3. Settings (.env) --------------------------------------------------------------------------
step "Settings in $DIR/.env"
[ -f .env ] || cp .env.example .env
chmod 600 .env
env_get() { python3 - "$1" <<'PY'
import sys, re
val = ""
for line in open(".env"):
    m = re.match(r"^" + re.escape(sys.argv[1]) + r"=(.*)$", line.rstrip("\n"))
    if m:
        val = m.group(1).strip().strip("'\"")
print(val)
PY
}
env_set() { python3 - "$1" "$2" <<'PY'
import sys, re
key, value = sys.argv[1], sys.argv[2]
lines = open(".env").read().splitlines()
pattern = re.compile(r"^" + re.escape(key) + r"=")
hits = [i for i, l in enumerate(lines) if pattern.match(l)]
if hits:
    lines[hits[-1]] = f"{key}={value}"
else:
    lines.append(f"{key}={value}")
open(".env", "w").write("\n".join(lines) + "\n")
PY
}
secret() { openssl rand -hex 32; }
ask_secret() {  # ask_secret KEY "prompt": keep the .env value, else take the environment, else ask
  local cur; cur="$(env_get "$1")"
  [ -n "$cur" ] && return 0
  local val="${!1:-}"
  if [ -z "$val" ]; then read -r -s -p "$2: " val; echo; fi
  [ -n "$val" ] || die "$1 is required"
  env_set "$1" "$val"
}

project="$(basename "$DIR" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"
fresh_db=1
$DOCKER volume inspect "${project}_pgdata" >/dev/null 2>&1 && fresh_db=0
if [ "$fresh_db" -eq 1 ]; then
  # Database passwords only take effect when the database is first created, so set them now.
  for key in POSTGRES_PASSWORD PMS_READONLY_PASSWORD PMS_APP_PASSWORD; do
    case "$(env_get $key)" in ""|pms|pms_readonly|pms_app) env_set "$key" "$(secret)" ;; esac
  done
fi
db_name="$(env_get POSTGRES_DB)"; db_user="$(env_get POSTGRES_USER)"
env_set PMS_APP_DATABASE_URL "postgresql://pms_app:$(env_get PMS_APP_PASSWORD)@db:5432/${db_name:-pms}"
ask_secret ANTHROPIC_API_KEY "Anthropic API key (input hidden)"
ask_secret CLOUDFLARE_TUNNEL_TOKEN "Cloudflare tunnel token (input hidden)"
[ -n "$(env_get WEB_SESSION_SECRET)" ] || env_set WEB_SESSION_SECRET "$(secret)"
[ -n "$(env_get PMS_MCP_SERVICE_TOKEN)" ] || env_set PMS_MCP_SERVICE_TOKEN "$(secret)"
[ -n "$(env_get WEB_AUTH)" ] || env_set WEB_AUTH password   # sign in with user accounts
env_set PMS_USER_DIRECTORY true
env_set WEB_PUBLIC_URL "https://$HOSTNAME_"
env_set WEB_TRUST_PROXY true
echo "Saved (secrets not shown). Sign-in: WEB_AUTH=$(env_get WEB_AUTH)"

# --- 4. Database, data, services and tunnel ------------------------------------------------------
compose() { $DOCKER compose --profile tunnel "$@"; }

step "Starting the database"
compose up -d db
for _ in $(seq 60); do
  compose exec -T db pg_isready -q -U "${db_user:-pms}" >/dev/null 2>&1 && break
  sleep 2
done
compose exec -T db pg_isready -q -U "${db_user:-pms}" >/dev/null 2>&1 || die "the database didn't start; see: $DOCKER compose logs db"

if [ "$SEED" -eq 1 ]; then
  step "Loading the sample data (first run only, about a minute)"
  compose run --rm seed
fi

step "Building and starting the MCP server, agent, website and tunnel (a few minutes the first time)"
compose up -d --build mcp agent web
compose up -d tunnel
if [ -n "$(env_get FNS_USER)" ]; then
  echo "FNS settings found: starting the daily FNSrooms import"
  compose --profile fns up -d --build fns-sync
fi

# --- 5. First administrator ----------------------------------------------------------------------
for _ in $(seq 60); do
  compose exec -T agent python -m pms_agent.admin list >/dev/null 2>&1 && break
  sleep 2
done
if [ "$ADMIN" -eq 0 ]; then
  :
elif ! compose exec -T agent python -m pms_agent.admin list 2>/dev/null | grep -q " admin "; then
  step "Creating the first administrator"
  [ -n "$ADMIN_EMAIL" ] || read -r -p "Administrator email: " ADMIN_EMAIL
  [ -n "$ADMIN_NAME" ] || read -r -p "Administrator name: " ADMIN_NAME
  compose exec agent python -m pms_agent.admin create-admin --email "$ADMIN_EMAIL" --name "$ADMIN_NAME"
elif [ -n "$ADMIN_EMAIL" ]; then
  echo "An administrator already exists; to reset a password run:"
  echo "  cd $DIR && sudo docker compose exec agent python -m pms_agent.admin create-admin --email $ADMIN_EMAIL --name \"$ADMIN_NAME\""
fi

# --- 6. Checks -----------------------------------------------------------------------------------
step "Checking"
code=""
for _ in $(seq 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:${PMS_WEB_PORT:-5050}/ || true)"
  [[ "$code" =~ ^(200|302|303|307|401)$ ]] && break
  sleep 2
done
[[ "$code" =~ ^(200|302|303|307|401)$ ]] && echo "Website answers locally (HTTP $code)." \
  || echo "WARNING: the website doesn't answer yet (HTTP ${code:-none}); see: $DOCKER compose logs web"
if compose logs tunnel 2>/dev/null | grep -q "Registered tunnel connection"; then
  echo "Tunnel connected to Cloudflare."
else
  echo "WARNING: no tunnel connection yet; check the token and: $DOCKER compose --profile tunnel logs tunnel"
fi

cat <<EOF

Done. Open https://$HOSTNAME_ and sign in as the administrator, then add people under Admin.
(The address works once the tunnel's public hostname points to http://web:5050 in Cloudflare.)

Useful commands (in $DIR):
  sudo docker compose ps                                  # what is running
  sudo docker compose logs -f agent                       # agent log
  sudo docker compose --profile tunnel logs -f tunnel     # tunnel log
  bash scripts/deploy_ubuntu.sh --hostname $HOSTNAME_      # update to the latest $BRANCH
EOF
}

main "$@"
