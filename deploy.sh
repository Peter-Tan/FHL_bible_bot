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
sleep 3
curl -sf http://127.0.0.1:7861/bible_bot/api/health && echo

echo "[5/5] Smoke tests..."
node e2e/verify-smoke.mjs

echo "Done. Live at https://tech.fhl.net/bible_bot/"
