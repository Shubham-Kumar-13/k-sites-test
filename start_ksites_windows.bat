@echo off
REM K-Sites Windows auto-start script
REM Starts the Flask backend and ngrok with the static domain, and restarts them if they crash.

REM Set environment variables
set KSITES_ACCESS_TOKEN=token
set KSITES_ALLOWED_ORIGINS=https://shubham-kumar-13.github.io
set KSITES_DATA_DIR=C:\Users\HP\Desktop\Work\K-Sites\webapp\results
set KSITES_EVIDENCE_DIR=C:\Users\HP\Desktop\Work\K-Sites\webapp\results\evidence-data
set K_SITES_NCBI_EMAIL=user@example.com
set KSITES_DATABASE_URI=postgresql+psycopg2://ksites:ksites123@localhost:5432/ksites

REM Change to the K-Sites directory
cd /d "C:\Users\HP\Desktop\Work\K-Sites"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found at .venv\Scripts\python.exe
    pause
    exit /b 1
)

REM Start the watchdog (it will start backend + ngrok and restart on crash)
".venv\Scripts\python.exe" tools\windows_startup.py
