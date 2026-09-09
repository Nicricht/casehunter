@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m casehunter verify
if errorlevel 1 (
  echo Tests failed. Server will not start.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8000
python -m casehunter serve
