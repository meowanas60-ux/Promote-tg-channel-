#!/usr/bin/env bash
set -e
python -u main.py & P1=$!
python -u bot.py & P2=$!
trap 'kill $P1 $P2 2>/dev/null || true' SIGTERM SIGINT
wait -n $P1 $P2
