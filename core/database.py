import sqlite3
import json
import os
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("Database")

class Database:
    def __init__(self, db_path="minecraft_bot.db"):
        self.db_path = os.path.join(os.path.dirname(__file__), db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        with self.conn:
            # Oyuncular
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    username TEXT PRIMARY KEY,
                    first_seen TEXT,
                    last_seen TEXT,
                    total_messages INTEGER DEFAULT 0,
                    trust_score INTEGER DEFAULT 10,
                    notes TEXT DEFAULT ''
                )
            """)

            # Önemli Dünya Konumları (Ev, Maden, Sandık vb.)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS locations (
                    name TEXT PRIMARY KEY,
                    x REAL,
                    y REAL,
                    z REAL,
                    description TEXT DEFAULT '',
                    created_by TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Sohbet Geçmişi
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT,
                    message TEXT,
                    role TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def save_location(self, name: str, x: float, y: float, z: float, description: str = "", created_by: str = ""):
        """Önemli bir Minecraft koordinatını hafızaya kaydeder."""
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO locations (name, x, y, z, description, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name.lower(), x, y, z, description, created_by))

    def get_location(self, name: str) -> Optional[Dict[str, Any]]:
        """Kaydedilmiş konumu getirir."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM locations WHERE name = ?", (name.lower(),))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_locations(self) -> List[Dict[str, Any]]:
        """Tüm kayıtlı yerleri listeler."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM locations ORDER BY name ASC")
        return [dict(row) for row in cur.fetchall()]

    def log_chat(self, sender: str, message: str, role: str = "user"):
        """Sohbet mesajını kaydeder."""
        with self.conn:
            self.conn.execute("""
                INSERT INTO chat_history (sender, message, role)
                VALUES (?, ?, ?)
            """, (sender, message, role))

    def update_player(self, username: str):
        """Oyuncunun görülme ve mesaj sayısını günceller."""
        with self.conn:
            self.conn.execute("""
                INSERT INTO players (username, first_seen, last_seen, total_messages)
                VALUES (?, datetime('now'), datetime('now'), 1)
                ON CONFLICT(username) DO UPDATE SET
                    last_seen = datetime('now'),
                    total_messages = total_messages + 1
            """, (username,))
