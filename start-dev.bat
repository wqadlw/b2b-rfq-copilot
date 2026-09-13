@echo off
title b2b-rfq-copilot dev
echo [1/2] starting engine on port 8000 ...
start "rfq-engine" cmd /k "cd /d D:\AAAAA\b2b-rfq-copilot && .venv\Scripts\uvicorn.exe rfq_copilot.app.main:app --host 127.0.0.1 --port 8000"
echo [2/2] starting frontend on port 5173 ...
start "rfq-frontend" cmd /k "cd /d D:\AAAAA\b2b-rfq-copilot\frontend && pnpm dev"
echo.
echo engine:  http://127.0.0.1:8000/api/v1/health
echo widget:  http://localhost:5173
echo.
echo (minimize the two windows; closing a window stops that service)
pause
