@echo off
echo Starting server with uvicorn...
echo.
cd /d "%~dp0"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pause

