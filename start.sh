#!/usr/bin/env bash
set -Eeuo pipefail

echo "🚀 Starting Visual Prompt AI system..."

python -u bot.py &
BOT_PID=$!

python -u main.py &
MAIN_PID=$!

echo "🤖 bot.py started with PID: $BOT_PID"
echo "📡 main.py started with PID: $MAIN_PID"

cleanup() {
    kill "$BOT_PID" "$MAIN_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

while true; do
    if ! kill -0 "$BOT_PID" 2>/dev/null; then
        echo "❌ bot.py stopped. Restarting..."
        python -u bot.py &
        BOT_PID=$!
    fi

    if ! kill -0 "$MAIN_PID" 2>/dev/null; then
        echo "❌ main.py stopped. Restarting..."
        python -u main.py &
        MAIN_PID=$!
    fi

    sleep 10
done
