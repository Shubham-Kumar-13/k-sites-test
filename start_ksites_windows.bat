@echo off
REM K-Sites Windows auto-start script
REM Starts the Flask backend and ngrok, and restarts them if they crash.

cd /d "C:\Users\HP\Desktop\Work\K-Sites"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found at .venv\Scripts\python.exe
    pause
    exit /b 1
)

".venv\Scripts\python.exe" tools\windows_startup.py
