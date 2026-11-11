#!/usr/bin/env bash
# Sets everything up the first time, then starts the app. Mac and Linux.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate

if [ ! -f .venv/.installed ]; then
  echo "Installing packages (first run only, this can take a few minutes)..."
  if ! pip install -q -r requirements.txt; then
    echo "Voice packages failed to install. Continuing with typed input only."
    pip install -q "fastapi>=0.115" "uvicorn[standard]>=0.34" "httpx>=0.27" "numpy>=1.26"
  fi
  touch .venv/.installed
fi

exec python app.py
