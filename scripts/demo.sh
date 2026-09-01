#!/usr/bin/env bash
set -euo pipefail
API="${API:-http://localhost:8000}"

echo "== health =="
curl -sf "$API/health" | tee /dev/stderr
echo

echo "== create campaign =="
CID=$(curl -sf -X POST "$API/api/campaigns" -H 'content-type: application/json' \
  -d '{"name":"demo","pacing_mode":"auto","provider_name":"mock_a","time_scale":60,"overdial_allowance":5}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "campaign $CID"

echo "== seed =="
curl -sf -X POST "$API/api/campaigns/$CID/seed" -H 'content-type: application/json' \
  -d '{"agents":50,"contacts":300,"answer_rate":0.5,"talk_sec":90}'
echo

echo "== start =="
curl -sf -X POST "$API/api/campaigns/$CID/start"
echo
echo "Open http://localhost:5173 and select the campaign."
echo "Try chaos: drop agents, provider failing, force progressive."
echo "Campaign id: $CID"
