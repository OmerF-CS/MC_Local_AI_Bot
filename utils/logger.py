import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

def setup_logging(config=None):
    """Merkezi loglama yapılandırması."""
    # Windows'ta stdout encoding düzeltmesi
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            pass

    log_level_str = getattr(config, "LOG_LEVEL", "INFO") if config else "INFO"
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    # Kök logger'ı temizle (Çift loglamayı önlemek için)
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            root.removeHandler(handler)

    root.setLevel(log_level)

    log_format = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    # Konsol çıktısı
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # Dosya çıktısı (Rotating File)
    try:
        if not os.path.exists("logs"):
            os.makedirs("logs", exist_ok=True)
            
        file_handler = RotatingFileHandler(
            "logs/minecraft_bot.log",
            maxBytes=5*1024*1024, # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception as e:
        logging.error(f"Dosya loglayıcı kurulamadı: {e}")

    # Harici kütüphanelerin gürültüsünü kıs
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

def get_logger(name: str) -> logging.Logger:
    """Modüllere logger verir."""
    return logging.getLogger(name)
