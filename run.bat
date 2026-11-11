@echo off
rem Sets everything up the first time, then starts the app. Windows.
cd /d "%~dp0"

if not exist .venv (
  python -m venv .venv
  if errorlevel 1 (
    echo Python was not found. Install it from python.org and tick "Add Python to PATH".
    pause
    exit /b 1
  )
)
call .venv\Scripts\activate.bat

if not exist .venv\.installed (
  echo Installing packages ^(first run only, this can take a few minutes^)...
  pip install -q -r requirements.txt
  if errorlevel 1 (
    echo Voice packages failed to install. Continuing with typed input only.
    pip install -q "fastapi>=0.115" "uvicorn[standard]>=0.34" "httpx>=0.27" "numpy>=1.26"
  )
  type nul > .venv\.installed
)

python app.py
pause
