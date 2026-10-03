@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo   🎮 Starting MC Local AI Bot (Ollama + Mineflayer)
echo =======================================================
echo.

:: Ensure .env exists
if not exist .env (
    echo [*] .env not found. Creating default from .env.example...
    copy .env.example .env >nul
)

:: Check if Ollama is running
curl -s http://localhost:11434 >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Ollama server does not seem to be running on http://localhost:11434.
    echo [*] Attempting to start Ollama in background...
    start /b ollama serve >nul 2>&1
    timeout /t 2 /nobreak >nul
)

echo [*] Launching Python AI Orchestrator and Mineflayer Worker...
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Bot exited with error code %errorlevel%.
    pause
)
