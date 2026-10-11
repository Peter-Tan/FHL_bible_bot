#!/bin/bash
# Deploy the new-UI stack (FastAPI + React, port 7861) on the server.
# The legacy Gradio service (fhl-bible-bot, port 7860) is deliberately untouched.
set -e

cd /home/fhl/peter/fhl_bible_tool/FHL_bible_tool_bot-main

echo "[1/5] Pulling latest code from GitHub..."
git pull origin main

echo "[2/5] Installing any new backend dependencies..."
.venv/bin/pip install -q -r requirements.txt

echo "[3/5] Building frontend..."
cd web && npm ci --silent && npm run build && cd ..

echo "[4/5] Restarting service..."
systemctl --user restart fhl-bible-ui.service
# Poll the health endpoint until the service answers (startup time varies),
# giving up after HEALTH_MAX_TRIES so a broken service can't hang the deploy.
HEALTH_MAX_TRIES=30   # × 2s interval ≈ 60s cap
for i in $(seq 1 "$HEALTH_MAX_TRIES"); do
  if curl -sf --max-time 5 http://127.0.0.1:7861/bible_bot/api/health; then
    echo " (healthy after ${i} tries)"
    break
  fi
  if [ "$i" -eq "$HEALTH_MAX_TRIES" ]; then
    echo "ERROR: service not healthy after ${HEALTH_MAX_TRIES} tries (~$((HEALTH_MAX_TRIES * 2))s) — check logs/uvicorn_ui.log" >&2
    systemctl --user status fhl-bible-ui.service --no-pager | head -15 >&2
    exit 1
  fi
  sleep 2
done

echo "[5/5] Smoke tests..."
node e2e/verify-smoke.mjs

echo "Done. Live at https://tech.fhl.net/bible_bot/"
