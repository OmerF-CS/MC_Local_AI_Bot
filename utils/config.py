import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _safe_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

@dataclass
class Config:
    # Minecraft Server Settings
    MINECRAFT_HOST: str = "localhost"
    MINECRAFT_PORT: int = 25565
    MINECRAFT_USERNAME: str = "AIAssistant"
    MINECRAFT_VERSION: str = ""
    
    # Local AI (Ollama) Settings
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    
    # WebSocket Bridge Settings
    BRIDGE_HOST: str = "127.0.0.1"
    BRIDGE_PORT: int = 8765
    
    # Bot and Personality Settings
    BOT_NAME: str = "AIAssistant"
    BOT_OWNER: str = "Omer"
    LOG_LEVEL: str = "INFO"
    COMMAND_PREFIX: str = "!"
    
    # Communication / Cooldown
    COOLDOWN_SECONDS: float = 0.2

    # Run and Database Isolation
    RUN_ID: str = ""
    DB_PATH: str = "minecraft_bot.db"

    @classmethod
    def load_from_env(cls) -> "Config":
        """Loads configuration from environment variables or .env file."""
        load_dotenv(override=True)
        
        return cls(
            MINECRAFT_HOST=os.getenv("MINECRAFT_HOST", "localhost"),
            MINECRAFT_PORT=_safe_int(os.getenv("MINECRAFT_PORT"), 25565),
            MINECRAFT_USERNAME=os.getenv("MINECRAFT_USERNAME", "AIAssistant"),
            MINECRAFT_VERSION=os.getenv("MINECRAFT_VERSION", ""),
            
            OLLAMA_BASE_URL=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            OLLAMA_MODEL=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            
            BRIDGE_HOST=os.getenv("BRIDGE_HOST", "127.0.0.1"),
            BRIDGE_PORT=_safe_int(os.getenv("BRIDGE_PORT"), 8765),
            
            BOT_NAME=os.getenv("BOT_NAME", "AIAssistant"),
            BOT_OWNER=os.getenv("BOT_OWNER", "Omer"),
            LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
            COMMAND_PREFIX=os.getenv("COMMAND_PREFIX", "!"),
            COOLDOWN_SECONDS=_safe_float(os.getenv("COOLDOWN_SECONDS"), 0.2),
            RUN_ID=os.getenv("MC_RUN_ID", ""),
            DB_PATH=os.getenv("MC_DB_PATH", "minecraft_bot.db")
        )
    
    def validate(self) -> List[str]:
        """Validates missing or invalid critical settings."""
        missing = []
        if not self.MINECRAFT_HOST:
            missing.append("MINECRAFT_HOST")
        if not self.MINECRAFT_USERNAME:
            missing.append("MINECRAFT_USERNAME")
        if not self.OLLAMA_BASE_URL:
            missing.append("OLLAMA_BASE_URL")
        if not self.OLLAMA_MODEL:
            missing.append("OLLAMA_MODEL")
        return missing
