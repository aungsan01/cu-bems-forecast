@echo off
REM Start the CU-BEMS forecasting app on Windows, then open http://127.0.0.1:8000
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (set PY=.venv\Scripts\python.exe) else (set PY=python)
echo Starting app... open http://127.0.0.1:8000 in your browser (Ctrl+C to stop)
%PY% -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
pause
