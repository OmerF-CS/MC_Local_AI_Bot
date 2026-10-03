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

            # Oyun İlerlemesi ve Kilometre Taşları (Progression Checkpoints)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS progression_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stage TEXT,
                    target TEXT,
                    inventory_json TEXT DEFAULT '{}',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Çoklu Görev Kuyruğu (Task Queue)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS task_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instruction TEXT,
                    primary_action TEXT,
                    assigned_by TEXT,
                    priority INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME
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

    # --- OYUN İLERLEME SİSTEMİ (PROGRESSION CHECKPOINTS) ---

    def save_progression(self, stage: str, target: str, inventory: Optional[Dict[str, int]] = None):
        """Ulaşılan yeni tech tree seviyesini veritabanına kaydeder."""
        inv_str = json.dumps(inventory or {})
        with self.conn:
            self.conn.execute("""
                INSERT INTO progression_checkpoints (stage, target, inventory_json)
                VALUES (?, ?, ?)
            """, (stage, target, inv_str))
            logger.info(f"💾 Progression checkpoint saved: {stage} -> {target}")

    def get_latest_progression(self) -> Optional[Dict[str, Any]]:
        """En son kaydedilmiş ilerleme seviyesini döner."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM progression_checkpoints
            ORDER BY id DESC LIMIT 1
        """)
        row = cur.fetchone()
        if not row:
            return None
        res = dict(row)
        try:
            res["inventory"] = json.loads(res.get("inventory_json", "{}"))
        except Exception:
            res["inventory"] = {}
        return res

    # --- ÇOKLU GÖREV KUYRUĞU (TASK QUEUE) ---

    def add_task(self, instruction: str, primary_action: str = "", assigned_by: str = "", priority: int = 1) -> int:
        """Kuyruğa yeni bir oyuncu veya otonom görev ekler."""
        with self.conn:
            cur = self.conn.execute("""
                INSERT INTO task_queue (instruction, primary_action, assigned_by, priority, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (instruction, primary_action, assigned_by, priority))
            return cur.lastrowid

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """Bekleyen görevleri öncelik sırasına göre listeler."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM task_queue
            WHERE status = 'pending'
            ORDER BY priority DESC, id ASC
        """)
        return [dict(row) for row in cur.fetchall()]

    def update_task_status(self, task_id: int, status: str):
        """Görev durumunu günceller."""
        with self.conn:
            completed_clause = ", completed_at = datetime('now')" if status in ("completed", "cancelled") else ""
            self.conn.execute(f"""
                UPDATE task_queue
                SET status = ? {completed_clause}
                WHERE id = ?
            """, (status, task_id))

    def complete_task(self, task_id: int):
        """Görevi tamamlandı olarak işaretler."""
        self.update_task_status(task_id, "completed")

    def clear_pending_tasks(self):
        """Bekleyen tüm görevleri temizler."""
        with self.conn:
            self.conn.execute("UPDATE task_queue SET status = 'cancelled' WHERE status = 'pending'")
