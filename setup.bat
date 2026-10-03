@echo off
setlocal enabledelayedexpansion

echo =======================================================
echo   🚀 MC Local AI Bot - Setup & Installation Wizard
echo =======================================================
echo.

:: 1. Check Python
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10+ is required but not found in PATH!
    echo Please install Python from https://www.python.org/ and check "Add Python to PATH".
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
echo  - Detected Python %PY_VER%

:: 2. Check Node.js
echo.
echo [2/5] Checking Node.js installation...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js 18+ is required but not found in PATH!
    echo Please install Node.js from https://nodejs.org/
    pause
    exit /b 1
)
for /f "tokens=1" %%i in ('node --version 2^>^&1') do set NODE_VER=%%i
echo  - Detected Node.js %NODE_VER%

:: 3. Check & Pull Ollama Model
echo.
echo [3/5] Checking Ollama & Qwen 2.5 3B model...
ollama --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Ollama was not found in PATH.
    echo If you are running Ollama remotely or in Docker, make sure OLLAMA_BASE_URL is reachable.
) else (
    echo  - Pulling recommended local model 'qwen2.5:3b' (lightweight and fast)...
    ollama pull qwen2.5:3b
)

:: 4. Install Python Dependencies
echo.
echo [4/5] Installing Python dependencies (pip)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install Python dependencies!
    pause
    exit /b 1
)

:: 5. Install Node.js Mineflayer Dependencies
echo.
echo [5/5] Installing Node.js Mineflayer worker dependencies (npm)...
pushd minecraft_bot
call npm install
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install npm packages in minecraft_bot!
    popd
    pause
    exit /b 1
)
popd

:: Setup .env if missing
if not exist .env (
    echo.
    echo [*] Creating .env file from .env.example...
    copy .env.example .env >nul
    echo  - Created .env. You can customize server IP and BOT_OWNER anytime.
)

echo.
echo =======================================================
echo   ✅ Setup Completed Successfully!
echo   Run 'run.bat' to start the autonomous Minecraft AI bot.
echo =======================================================
echo.
pause
