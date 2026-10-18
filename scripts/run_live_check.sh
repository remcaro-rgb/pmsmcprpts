#!/usr/bin/env bash
# Run the live check (scripts/live_check.py) on one Claude model and zip the results.
#
#   scripts/run_live_check.sh claude-haiku-5-5
#   scripts/run_live_check.sh claude-sonnet-5-5 --langs es
#
# Rebuilds the MCP server and agent from this checkout with PMS_CLAUDE_MODEL set to the model,
# waits until the agent reports it, runs the 14 questions (extra arguments go to live_check.py),
# zips the run folder to live-check-<model>.zip, then restarts the agent on its usual model
# (PMS_CLAUDE_MODEL from .env, or the default). Needs ANTHROPIC_API_KEY in .env.
set -euo pipefail

model="${1:?usage: scripts/run_live_check.sh <model> [live_check.py options]}"
shift
cd "$(dirname "$0")/.."
agent="${PMS_AGENT_URL:-http://localhost:${PMS_AGENT_PORT:-7001}}"

echo "Starting the MCP server and agent on $model ..."
PMS_CLAUDE_MODEL="$model" docker compose up -d --build mcp agent

for _ in $(seq 60); do
  served=$(curl -fsS "$agent/api/health" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["model"])' 2>/dev/null || true)
  [ "$served" = "$model" ] && break
  sleep 2
done
if [ "$served" != "$model" ]; then
  echo "The agent at $agent reports '${served:-nothing}', not $model; see: docker compose logs agent" >&2
  exit 1
fi

python3 scripts/live_check.py --agent "$agent" "$@"

dir=$(ls -dt live-check/"$model"-*/ | head -1)
zip -qr "live-check-$model.zip" "$dir" -x '*.DS_Store'
echo "Zipped $dir -> live-check-$model.zip"

echo "Restarting the agent on its usual model ..."
docker compose up -d agent
