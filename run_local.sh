#!/usr/bin/env bash
# Start the CU-BEMS forecasting app on macOS/Linux, then open http://127.0.0.1:8000
cd "$(dirname "$0")"
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
echo "Starting app... open http://127.0.0.1:8000 (Ctrl+C to stop)"
"$PY" -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
