#!/usr/bin/env bash
set -u
echo "🚀 Starting VisualPrompt AI..."
python -u bot.py & BOT_PID=$!
sleep 3
python -u main.py & MAIN_PID=$!
echo "🟢 Bot PID: $BOT_PID | Monitor PID: $MAIN_PID"
while true; do
  if ! kill -0 "$BOT_PID" 2>/dev/null; then kill "$MAIN_PID" 2>/dev/null || true; exit 1; fi
  if ! kill -0 "$MAIN_PID" 2>/dev/null; then kill "$BOT_PID" 2>/dev/null || true; exit 1; fi
  sleep 10
done
