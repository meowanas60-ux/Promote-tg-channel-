#!/usr/bin/env bash
set -e

exec gunicorn main:app --bind 0.0.0.0:${PORT:-10000} --workers 1
