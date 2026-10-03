#!/usr/bin/env bash
set -e

echo "======================================================="
echo "  🚀 MC Local AI Bot - Setup & Installation Wizard"
echo "======================================================="
echo ""

# 1. Check Python
echo "[1/5] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 is required but not found!"
    exit 1
fi
python3 --version

# 2. Check Node.js
echo ""
echo "[2/5] Checking Node.js installation..."
if ! command -v node &> /dev/null; then
    echo "[ERROR] Node.js 18+ is required but not found!"
    exit 1
fi
node --version

# 3. Check Ollama
echo ""
echo "[3/5] Checking Ollama & Qwen 2.5 3B model..."
if command -v ollama &> /dev/null; then
    echo " - Pulling recommended local model 'qwen2.5:3b'..."
    ollama pull qwen2.5:3b || true
else
    echo "[WARNING] Ollama CLI not found in PATH."
fi

# 4. Install Python Dependencies
echo ""
echo "[4/5] Installing Python dependencies (pip)..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

# 5. Install Node.js Mineflayer Dependencies
echo ""
echo "[5/5] Installing Node.js Mineflayer worker dependencies (npm)..."
cd minecraft_bot
npm install
cd ..

# Setup .env if missing
if [ ! -f .env ]; then
    echo ""
    echo "[*] Creating .env from .env.example..."
    cp .env.example .env
fi

echo ""
echo "======================================================="
echo "  ✅ Setup Completed Successfully!"
echo "  Run './run.sh' to start the autonomous Minecraft bot."
echo "======================================================="
