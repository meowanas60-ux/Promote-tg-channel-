#!/bin/bash
set -e

python bot.py &
BOT_PID=$!

python main.py &
MAIN_PID=$!

cleanup() {
  kill "$BOT_PID" "$MAIN_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

while true; do
  if ! kill -0 "$BOT_PID" 2>/dev/null; then
    echo "bot.py stopped; restarting..."
    python bot.py &
    BOT_PID=$!
  fi

  if ! kill -0 "$MAIN_PID" 2>/dev/null; then
    echo "main.py stopped; restarting..."
    python main.py &
    MAIN_PID=$!
  fi

  sleep 15
done
