import sqlite3
from pathlib import Path
from datetime import datetime


class Store:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_topics (
                topic_id INTEGER PRIMARY KEY,
                title TEXT,
                discovered_at TEXT,
                has_key INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS found_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_value TEXT UNIQUE,
                key_type TEXT,
                region TEXT DEFAULT '',
                base_url TEXT DEFAULT '',
                topic_id INTEGER,
                valid INTEGER,
                verified_at TEXT,
                discovered_at TEXT,
                FOREIGN KEY (topic_id) REFERENCES seen_topics(topic_id)
            );
        """)
        # 迁移：为旧表添加 region/base_url 列
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(found_keys)").fetchall()}
        if "region" not in cols:
            self.conn.execute("ALTER TABLE found_keys ADD COLUMN region TEXT DEFAULT ''")
        if "base_url" not in cols:
            self.conn.execute("ALTER TABLE found_keys ADD COLUMN base_url TEXT DEFAULT ''")
        self.conn.commit()

    def is_topic_seen(self, topic_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen_topics WHERE topic_id = ?", (topic_id,)
        ).fetchone()
        return row is not None

    def mark_topic_seen(self, topic_id: int, title: str, has_key: bool = False):
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_topics (topic_id, title, discovered_at, has_key) VALUES (?, ?, ?, ?)",
            (topic_id, title, datetime.now().isoformat(), int(has_key)),
        )
        self.conn.commit()

    def is_key_known(self, key_value: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM found_keys WHERE key_value = ?", (key_value,)
        ).fetchone()
        return row is not None

    def save_key(self, key_value: str, key_type: str, topic_id: int, valid: int, region: str = "", base_url: str = ""):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO found_keys (key_value, key_type, region, base_url, topic_id, valid, verified_at, discovered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (key_value, key_type, region, base_url, topic_id, valid, now, now),
        )
        self.conn.commit()

    def update_key_validity(self, key_value: str, valid: int):
        self.conn.execute(
            "UPDATE found_keys SET valid = ?, verified_at = ? WHERE key_value = ?",
            (valid, datetime.now().isoformat(), key_value),
        )
        self.conn.commit()

    def get_valid_keys(self) -> list[dict]:
        rows = self.conn.execute("""
            SELECT key_value, key_type, region, base_url, valid, topic_id, verified_at, discovered_at
            FROM found_keys ORDER BY discovered_at DESC
        """).fetchall()
        return [
            {
                "key": r[0],
                "type": r[1],
                "region": r[2] or "",
                "base_url": r[3] or "",
                "valid": r[4] == 1,
                "topic_id": r[5],
                "verified_at": r[6],
                "discovered_at": r[7],
            }
            for r in rows
        ]

    def close(self):
        self.conn.close()
