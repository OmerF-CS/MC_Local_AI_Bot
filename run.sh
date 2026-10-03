#!/usr/bin/env bash
set -e

echo "======================================================="
echo "  🎮 Starting MC Local AI Bot (Ollama + Mineflayer)"
echo "======================================================="
echo ""

if [ ! -f .env ]; then
    echo "[*] .env not found. Copying from .env.example..."
    cp .env.example .env
fi

if ! curl -s http://localhost:11434 > /dev/null 2>&1; then
    echo "[!] Ollama does not seem to be running on http://localhost:11434."
    if command -v ollama &> /dev/null; then
        echo "[*] Starting Ollama in background..."
        ollama serve > /dev/null 2>&1 &
        sleep 2
    fi
fi

echo "[*] Launching Python AI Orchestrator and Mineflayer Worker..."
python3 main.py
