import sqlite3
import json
import os
import logging
import math
from typing import List, Dict, Any, Optional, Tuple

from utils.run_context import get_current_run_id

logger = logging.getLogger("Database")

class Database:
    def __init__(self, db_path="minecraft_bot.db"):
        env_db = os.getenv("MC_DB_PATH")
        if env_db and (db_path == "minecraft_bot.db" or not db_path):
            chosen = env_db
        else:
            chosen = db_path

        if chosen == ":memory:" or os.path.isabs(chosen):
            self.db_path = chosen
        else:
            self.db_path = os.path.join(os.path.dirname(__file__), chosen)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        with self.conn:
            # Player Tracking
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

            # World Landmarks (Home, Base, Mines, Portal, etc.)
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

            # Chat History
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT,
                    message TEXT,
                    role TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Speedrun Progression Checkpoints
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS progression_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stage TEXT,
                    target TEXT,
                    inventory_json TEXT DEFAULT '{}',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Death Points & Corpse Recovery (F0.3)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS death_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dim TEXT DEFAULT 'overworld',
                    x REAL,
                    y REAL,
                    z REAL,
                    inventory_json TEXT DEFAULT '[]',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    recovered INTEGER DEFAULT 0
                )
            """)

            # Beds & Spawn Points (F1.1)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS beds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dim TEXT DEFAULT 'overworld',
                    x REAL,
                    y REAL,
                    z REAL,
                    used_for_spawn INTEGER DEFAULT 1,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Chest Storage (F1.5)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS chests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dim TEXT DEFAULT 'overworld',
                    x REAL,
                    y REAL,
                    z REAL,
                    items_json TEXT DEFAULT '[]',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Persistent Ore Map (Phase 2 / F2.2)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS ore_map (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dim TEXT DEFAULT 'overworld',
                    x INTEGER,
                    y INTEGER,
                    z INTEGER,
                    block TEXT,
                    mined INTEGER DEFAULT 0,
                    discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    mined_at DATETIME,
                    UNIQUE(dim, x, y, z)
                )
            """)

            # Task Queue
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS task_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instruction TEXT,
                    primary_action TEXT,
                    args_json TEXT DEFAULT '{}',
                    assigned_by TEXT,
                    priority INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME
                )
            """)

            # Lessons / Autonomous Memory (Phase 2)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT DEFAULT 'general',
                    lesson TEXT UNIQUE,
                    run_id TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Run Isolation & Metadata (Task 1)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    commit_hash TEXT DEFAULT '',
                    is_test INTEGER DEFAULT 0,
                    model_name TEXT DEFAULT '',
                    notes TEXT DEFAULT ''
                )
            """)

            # Hazard Memory Map (Phase 3)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS hazard_map (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dim TEXT DEFAULT 'overworld',
                    x REAL,
                    y REAL,
                    z REAL,
                    hazard_type TEXT,
                    radius REAL DEFAULT 5.0,
                    run_id TEXT DEFAULT '',
                    discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Column migrations: Ensure run_id exists in operational tables
            tables_to_migrate = [
                "progression_checkpoints",
                "death_points",
                "beds",
                "chests",
                "ore_map",
                "chat_history",
                "hazard_map"
            ]
            for tbl in tables_to_migrate:
                try:
                    cur = self.conn.execute(f"PRAGMA table_info({tbl})")
                    cols = [r["name"] for r in cur.fetchall()]
                    if "run_id" not in cols:
                        self.conn.execute(f"ALTER TABLE {tbl} ADD COLUMN run_id TEXT DEFAULT ''")
                except Exception as e:
                    logger.debug(f"Migration notice for {tbl}: {e}")

            try:
                self.conn.execute("ALTER TABLE task_queue ADD COLUMN args_json TEXT DEFAULT '{}'")
            except Exception:
                pass

    def record_run(self, run_id: Optional[str] = None, commit_hash: str = "", is_test: bool = False, model_name: str = "", notes: str = ""):
        """Records or updates a run record in the database."""
        rid = run_id or get_current_run_id()
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO runs (run_id, commit_hash, is_test, model_name, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (rid, commit_hash, 1 if is_test else 0, model_name, notes))

    def save_location(self, name: str, x: float, y: float, z: float, description: str = "", created_by: str = ""):
        """Saves a world coordinate with a name into memory."""
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO locations (name, x, y, z, description, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name.lower(), x, y, z, description, created_by))

    def get_location(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieves a saved landmark by name."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM locations WHERE name = ?", (name.lower(),))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_locations(self) -> List[Dict[str, Any]]:
        """Lists all saved landmarks."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM locations ORDER BY name ASC")
        return [dict(row) for row in cur.fetchall()]

    def log_chat(self, sender: str, message: str, role: str = "user", run_id: Optional[str] = None):
        """Logs chat messages to database."""
        rid = run_id or get_current_run_id()
        with self.conn:
            self.conn.execute("""
                INSERT INTO chat_history (sender, message, role, run_id)
                VALUES (?, ?, ?, ?)
            """, (sender, message, role, rid))

    def update_player(self, username: str):
        """Updates player metadata and interaction count."""
        with self.conn:
            self.conn.execute("""
                INSERT INTO players (username, first_seen, last_seen, total_messages)
                VALUES (?, datetime('now'), datetime('now'), 1)
                ON CONFLICT(username) DO UPDATE SET
                    last_seen = datetime('now'),
                    total_messages = total_messages + 1
            """, (username,))

    def get_player_trust(self, username: str) -> int:
        """Gets current player trust score clamped between 0 and 100 (default 10)."""
        if not username:
            return 10
        cur = self.conn.cursor()
        cur.execute("SELECT trust_score FROM players WHERE username = ?", (username,))
        row = cur.fetchone()
        if row and row["trust_score"] is not None:
            return max(0, min(100, int(row["trust_score"])))
        return 10

    def update_player_trust(self, username: str, delta: int) -> int:
        """Updates and clamps player trust score between 0 and 100."""
        if not username:
            return 10
        current_trust = self.get_player_trust(username)
        new_trust = max(0, min(100, current_trust + delta))
        with self.conn:
            self.conn.execute("""
                INSERT INTO players (username, first_seen, last_seen, trust_score)
                VALUES (?, datetime('now'), datetime('now'), ?)
                ON CONFLICT(username) DO UPDATE SET
                    trust_score = ?,
                    last_seen = datetime('now')
            """, (username, new_trust, new_trust))
        return new_trust

    def save_lesson(self, lesson: str, category: str = "general", run_id: Optional[str] = None) -> bool:
        """Saves a learned tactical or death lesson to persistent database."""
        if not lesson:
            return False
        rid = run_id or get_current_run_id()
        with self.conn:
            self.conn.execute("""
                INSERT OR IGNORE INTO lessons (category, lesson, run_id)
                VALUES (?, ?, ?)
            """, (category, lesson.strip(), rid))
            return True

    def get_recent_lessons(self, limit: int = 4) -> List[str]:
        """Retrieves the most recent unique lessons learned across runs."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT lesson FROM lessons
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        return [row["lesson"] for row in cur.fetchall()]

    # --- PROGRESSION CHECKPOINTS ---

    def save_progression(self, stage: str, target: str, inventory: Optional[Dict[str, int]] = None, run_id: Optional[str] = None):
        """Saves current milestone progression era to database."""
        inv_str = json.dumps(inventory or {})
        rid = run_id or get_current_run_id()
        with self.conn:
            self.conn.execute("""
                INSERT INTO progression_checkpoints (stage, target, inventory_json, run_id)
                VALUES (?, ?, ?, ?)
            """, (stage, target, inv_str, rid))
            logger.info(f"💾 Progression checkpoint saved: {stage} -> {target}")

    def get_latest_progression(self) -> Optional[Dict[str, Any]]:
        """Returns the most recent progression milestone checkpoint."""
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

    # --- MULTI-TASK QUEUE ---

    def add_task(self, instruction: str, primary_action: str = "", assigned_by: str = "", priority: int = 1, args: Optional[Dict[str, Any]] = None) -> int:
        """Adds a player or autonomous task to the queue."""
        args_str = json.dumps(args or {})
        with self.conn:
            cur = self.conn.execute("""
                INSERT INTO task_queue (instruction, primary_action, assigned_by, priority, status, args_json)
                VALUES (?, ?, ?, ?, 'pending', ?)
            """, (instruction, primary_action, assigned_by, priority, args_str))
            return cur.lastrowid

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """Lists pending tasks sorted by priority."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM task_queue
            WHERE status = 'pending'
            ORDER BY priority DESC, id ASC
        """)
        tasks = []
        for row in cur.fetchall():
            item = dict(row)
            try:
                item["args"] = json.loads(item.get("args_json", "{}"))
            except Exception:
                item["args"] = {}
            tasks.append(item)
        return tasks

    def update_task_status(self, task_id: int, status: str):
        """Updates task execution status."""
        with self.conn:
            if status in ("completed", "cancelled"):
                self.conn.execute("""
                    UPDATE task_queue
                    SET status = ?, completed_at = datetime('now')
                    WHERE id = ?
                """, (status, task_id))
            else:
                self.conn.execute("""
                    UPDATE task_queue
                    SET status = ?
                    WHERE id = ?
                """, (status, task_id))

    def complete_task(self, task_id: int):
        """Marks a task as completed."""
        self.update_task_status(task_id, "completed")

    def clear_pending_tasks(self):
        """Cancels all pending tasks in the queue."""
        with self.conn:
            self.conn.execute("UPDATE task_queue SET status = 'cancelled' WHERE status = 'pending'")

    # --- DEATH RECOVERY & CORPSE RECOVERY (F0.3) ---

    def save_death_point(self, dim: str, x: float, y: float, z: float, inventory: Optional[List[Dict[str, Any]]] = None, run_id: Optional[str] = None) -> int:
        """Records a bot death location and inventory snapshot for corpse recovery."""
        inv_str = json.dumps(inventory or [])
        rid = run_id or get_current_run_id()
        with self.conn:
            cur = self.conn.execute("""
                INSERT INTO death_points (dim, x, y, z, inventory_json, recovered, run_id)
                VALUES (?, ?, ?, ?, ?, 0, ?)
            """, (dim, x, y, z, inv_str, rid))
            return cur.lastrowid

    def get_unrecovered_death_point(self, dim: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Returns the most recent unrecovered death point."""
        cur = self.conn.cursor()
        if dim:
            cur.execute("""
                SELECT * FROM death_points
                WHERE recovered = 0 AND dim = ?
                ORDER BY id DESC LIMIT 1
            """, (dim,))
        else:
            cur.execute("""
                SELECT * FROM death_points
                WHERE recovered = 0
                ORDER BY id DESC LIMIT 1
            """)
        row = cur.fetchone()
        if not row:
            return None
        res = dict(row)
        try:
            res["inventory"] = json.loads(res.get("inventory_json", "[]"))
        except Exception:
            res["inventory"] = []
        return res

    def mark_death_point_recovered(self, death_id: int):
        """Marks a death point as recovered after items are collected."""
        with self.conn:
            self.conn.execute("""
                UPDATE death_points SET recovered = 1 WHERE id = ?
            """, (death_id,))
            logger.info(f"✅ Marked death point #{death_id} as successfully recovered!")

    # --- BEDS & SPAWN POINTS (F1.1) ---

    def save_bed_location(self, dim: str, x: float, y: float, z: float, is_spawn: bool = True, run_id: Optional[str] = None):
        """Saves a bed location and spawn status."""
        rid = run_id or get_current_run_id()
        with self.conn:
            self.conn.execute("""
                INSERT INTO beds (dim, x, y, z, used_for_spawn, run_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (dim, x, y, z, 1 if is_spawn else 0, rid))

    def get_latest_bed(self, dim: str = "overworld") -> Optional[Dict[str, Any]]:
        """Returns the latest known bed location in the given dimension."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM beds
            WHERE dim = ?
            ORDER BY id DESC LIMIT 1
        """, (dim,))
        row = cur.fetchone()
        return dict(row) if row else None

    # --- CHESTS & INVENTORY STORAGE (F1.5) ---

    def save_chest_location(self, dim: str, x: float, y: float, z: float, items: Optional[List[Dict[str, Any]]] = None, run_id: Optional[str] = None) -> int:
        """Saves or updates a chest location and snapshot of contents."""
        items_str = json.dumps(items or [])
        rid = run_id or get_current_run_id()
        with self.conn:
            cur = self.conn.execute("""
                INSERT INTO chests (dim, x, y, z, items_json, run_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (dim, x, y, z, items_str, rid))
            return cur.lastrowid

    def get_nearby_chests(self, dim: str = "overworld", x: float = 0.0, y: float = 0.0, z: float = 0.0, max_dist: float = 48.0) -> List[Dict[str, Any]]:
        """Returns chests located within max_dist blocks of given coordinates."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM chests
            WHERE dim = ?
            ORDER BY id DESC
        """, (dim,))
        nearby = []
        for row in cur.fetchall():
            c = dict(row)
            dist = ((c["x"] - x)**2 + (c["y"] - y)**2 + (c["z"] - z)**2) ** 0.5
            if dist <= max_dist:
                c["distance"] = dist
                try:
                    c["items"] = json.loads(c.get("items_json", "[]"))
                except Exception:
                    c["items"] = []
                nearby.append(c)
        nearby.sort(key=lambda item: item["distance"])
        return nearby

    # --- PERSISTENT ORE MAP (Phase 2 / F2.2) ---

    def save_ore(self, dim: str, x: int, y: int, z: int, block: str, run_id: Optional[str] = None) -> bool:
        """Saves a discovered ore vein coordinate to memory."""
        rid = run_id or get_current_run_id()
        with self.conn:
            self.conn.execute("""
                INSERT OR IGNORE INTO ore_map (dim, x, y, z, block, run_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (dim, int(x), int(y), int(z), block.lower(), rid))
            return True

    def get_unmined_ores(self, dim: str = "overworld", block_type: Optional[str] = None, x: float = 0.0, y: float = 0.0, z: float = 0.0, max_dist: float = 64.0) -> List[Dict[str, Any]]:
        """Finds unmined ores within max_dist, sorted by distance."""
        cur = self.conn.cursor()
        if block_type:
            cur.execute("""
                SELECT * FROM ore_map
                WHERE dim = ? AND mined = 0 AND (block = ? OR block LIKE ?)
                ORDER BY id DESC
            """, (dim, block_type.lower(), f"%{block_type.lower()}%"))
        else:
            cur.execute("""
                SELECT * FROM ore_map
                WHERE dim = ? AND mined = 0
                ORDER BY id DESC
            """, (dim,))
        
        ores = []
        for row in cur.fetchall():
            o = dict(row)
            dist = ((o["x"] - x)**2 + (o["y"] - y)**2 + (o["z"] - z)**2) ** 0.5
            if dist <= max_dist:
                o["distance"] = dist
                ores.append(o)
        ores.sort(key=lambda item: item["distance"])
        return ores

    def mark_ore_mined(self, dim: str, x: int, y: int, z: int):
        """Marks an ore as mined after collection."""
        with self.conn:
            self.conn.execute("""
                UPDATE ore_map
                SET mined = 1, mined_at = datetime('now')
                WHERE dim = ? AND x = ? AND y = ? AND z = ?
            """, (dim, int(x), int(y), int(z)))

    # --- HAZARD MEMORY MAP (Phase 3) ---

    def record_hazard(self, dim: str, x: float, y: float, z: float, hazard_type: str, radius: float = 5.0, run_id: Optional[str] = None) -> bool:
        """Records a dangerous hazard area (lava, void, mob spawner, cliff) to persistent memory."""
        rid = run_id or get_current_run_id()
        try:
            with self.conn:
                self.conn.execute("""
                    INSERT INTO hazard_map (dim, x, y, z, hazard_type, radius, run_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (str(dim).lower(), float(x), float(y), float(z), str(hazard_type).lower(), float(radius), rid))
            return True
        except Exception as e:
            logger.error(f"Failed to record hazard: {e}")
            return False

    def get_nearby_hazards(self, dim: str = "overworld", x: float = 0.0, z: float = 0.0, max_dist: float = 64.0) -> List[Dict[str, Any]]:
        """Returns recorded hazards within max_dist of (x, z) in given dimension, sorted by distance."""
        dim_clean = str(dim).lower()
        try:
            cur = self.conn.cursor()
            cur.execute("""
                SELECT id, dim, x, y, z, hazard_type, radius, run_id, discovered_at
                FROM hazard_map
                WHERE dim = ?
                ORDER BY id DESC
            """, (dim_clean,))
            hazards = []
            for r in cur.fetchall():
                rx = float(r["x"])
                rz = float(r["z"])
                dist = math.hypot(rx - x, rz - z)
                if dist <= max_dist:
                    item = dict(r)
                    item["distance"] = round(dist, 2)
                    hazards.append(item)
            hazards.sort(key=lambda h: h["distance"])
            return hazards
        except Exception as e:
            logger.error(f"Failed to get nearby hazards: {e}")
            return []

    def is_hazard_point(self, dim: str, x: float, z: float, margin: float = 4.0) -> bool:
        """Returns True if (x, z) is within (radius + margin) of any recorded hazard in dimension."""
        dim_clean = str(dim).lower()
        try:
            cur = self.conn.cursor()
            cur.execute("""
                SELECT x, z, radius
                FROM hazard_map
                WHERE dim = ?
            """, (dim_clean,))
            for r in cur.fetchall():
                rx = float(r["x"])
                rz = float(r["z"])
                rad = float(r["radius"])
                dist = math.hypot(rx - x, rz - z)
                if dist <= (rad + margin):
                    return True
            return False
        except Exception as e:
            logger.error(f"Failed to check hazard point: {e}")
            return False

    def close(self):
        """Closes the underlying SQLite database connection."""
        try:
            self.conn.close()
        except Exception:
            pass


