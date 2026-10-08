@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo   🚀 MC Local AI Bot - Windows Setup & Wizard
echo =======================================================
echo.

REM 1. Check Python
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 3.10+ is required but not found in PATH!
    pause
    exit /b 1
)
python --version

REM 2. Check Node.js
echo.
echo [2/5] Checking Node.js installation...
node --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js 18+ is required but not found in PATH!
    pause
    exit /b 1
)
node --version

REM 3. Check Ollama
echo.
echo [3/5] Checking Ollama & Model...
ollama --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo  - Pulling recommended local model 'qwen2.5:3b'...
    ollama pull qwen2.5:3b
) else (
    echo [WARNING] Ollama CLI not found in PATH. Ensure Ollama is installed and running.
)

REM 4. Install Python Dependencies
echo.
echo [4/5] Installing Python dependencies (pip)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to install Python dependencies.
    pause
    exit /b 1
)

REM 5. Install Mineflayer Node Dependencies
echo.
echo [5/5] Installing Mineflayer Node.js worker dependencies (npm)...
cd minecraft_bot
call npm install
cd ..

REM 6. Setup .env
if not exist .env (
    echo.
    echo [*] Creating .env from .env.example...
    copy .env.example .env >nul
)

echo.
echo =======================================================
echo   ✅ Windows Setup Completed Successfully!
echo   To launch the bot, run: python main.py
echo =======================================================
echo.
pause
