@echo off
chcp 65001 >nul
title b2b-rfq-copilot dev
echo [1/2] starting engine on http://127.0.0.1:8000 ...
start "rfq-engine" cmd /k "cd /d D:\AAAAA\b2b-rfq-copilot && .venv\Scripts\uvicorn.exe rfq_copilot.app.main:app --host 127.0.0.1 --port 8000"
echo [2/2] starting frontend on http://localhost:5173 ...
start "rfq-frontend" cmd /k "cd /d D:\AAAAA\b2b-rfq-copilot\frontend && pnpm dev"
echo.
echo engine : http://127.0.0.1:8000/api/v1/health
echo widget : http://localhost:5173
echo.
echo (两个窗口最小化即可, 关闭对应窗口即停服务)
pause
