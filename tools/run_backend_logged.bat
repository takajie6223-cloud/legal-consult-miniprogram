@echo off
chcp 65001 >nul
cd /d "%~dp0..\backend"
if not exist logs mkdir logs
if exist .venv\Scripts\python.exe (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 9100 >> logs\backend.log 2>&1
