#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PY=$(command -v python3.11 || command -v python3.12 || true)
[ -z "$PY" ] && { echo "Python 3.11 not found. Install it first (e.g. brew install python@3.11)."; exit 1; }
[ -d venv311 ] || "$PY" -m venv venv311
source venv311/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo; echo "Setup finished. Edit .env (add GEMINI_API_KEY and TAVILY_API_KEY), then run ./check.sh and ./start.sh"
