import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

@dataclass
class Config:
    # Minecraft Sunucu Ayarları
    MINECRAFT_HOST: str = "localhost"
    MINECRAFT_PORT: int = 25565
    MINECRAFT_USERNAME: str = "AIAssistant"
    MINECRAFT_VERSION: str = ""
    
    # Lokal AI (Ollama) Ayarları
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    
    # Köprü (Bridge) Ayarları
    BRIDGE_HOST: str = "127.0.0.1"
    BRIDGE_PORT: int = 8765
    
    # Bot ve Kişilik Ayarları
    BOT_NAME: str = "AIAssistant"
    BOT_OWNER: str = "Omer"
    LOG_LEVEL: str = "INFO"
    COMMAND_PREFIX: str = "!"
    
    # İletişim / Cooldown
    COOLDOWN_SECONDS: float = 1.0

    @classmethod
    def load_from_env(cls) -> "Config":
        """Ortam değişkenlerinden veya .env dosyasından konfigürasyonu yükler."""
        load_dotenv(override=True)
        
        return cls(
            MINECRAFT_HOST=os.getenv("MINECRAFT_HOST", "localhost"),
            MINECRAFT_PORT=int(os.getenv("MINECRAFT_PORT", 25565)),
            MINECRAFT_USERNAME=os.getenv("MINECRAFT_USERNAME", "AIAssistant"),
            MINECRAFT_VERSION=os.getenv("MINECRAFT_VERSION", ""),
            
            OLLAMA_BASE_URL=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            OLLAMA_MODEL=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            
            BRIDGE_HOST=os.getenv("BRIDGE_HOST", "127.0.0.1"),
            BRIDGE_PORT=int(os.getenv("BRIDGE_PORT", 8765)),
            
            BOT_NAME=os.getenv("BOT_NAME", "AIAssistant"),
            BOT_OWNER=os.getenv("BOT_OWNER", "Omer"),
            LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
            COMMAND_PREFIX=os.getenv("COMMAND_PREFIX", "!"),
            COOLDOWN_SECONDS=float(os.getenv("COOLDOWN_SECONDS", 1.0))
        )
    
    def validate(self) -> List[str]:
        """Eksik veya hatalı kritik ayarları doğrular."""
        missing = []
        if not self.MINECRAFT_HOST:
            missing.append("MINECRAFT_HOST")
        if not self.MINECRAFT_USERNAME:
            missing.append("MINECRAFT_USERNAME")
        if not self.OLLAMA_MODEL:
            missing.append("OLLAMA_MODEL")
        return missing
