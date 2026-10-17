import json
import sqlite3
from pathlib import Path


class StateManager:
    def __init__(self, directory: str) -> None:
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(Path(directory) / "progress.sqlite3")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS progress (endpoint TEXT PRIMARY KEY, document TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS reviews (identity TEXT PRIMARY KEY, document TEXT NOT NULL)")
        self.connection.execute("PRAGMA user_version=1")
        self.connection.commit()

    @staticmethod
    def identity(document: dict) -> str:
        return json.dumps([document["endpoint"], document["set_id"], document["image_id"], document["path"]])

    def save(self, document: dict) -> None:
        encoded = json.dumps(document, ensure_ascii=False)
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO progress VALUES (?, ?)", (document["endpoint"], encoded))
            self.connection.execute("INSERT OR REPLACE INTO reviews VALUES (?, ?)", (self.identity(document), encoded))

    def restore(self, endpoint: str) -> dict | None:
        row = self.connection.execute("SELECT document FROM progress WHERE endpoint=?", (endpoint,)).fetchone()
        return json.loads(row[0]) if row else None

    def review(self, endpoint: str, set_id: int, record: dict) -> dict | None:
        key = self.identity({"endpoint": endpoint, "set_id": set_id, "image_id": record["id"], "path": record["path"]})
        row = self.connection.execute("SELECT document FROM reviews WHERE identity=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def close(self) -> None:
        self.connection.close()