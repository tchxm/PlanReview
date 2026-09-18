import json, sqlite3
from pathlib import Path
from datetime import datetime, timezone


class Store:
    def __init__(self, path="data/planreview.sqlite"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, timestamp TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL)"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def save(self, task, kind, detail=None):
        with self.connect() as db:
            db.execute(
                "INSERT INTO tasks VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (task["id"], json.dumps(task)),
            )
            db.execute(
                "INSERT INTO events(task_id,timestamp,kind,body) VALUES (?,?,?,?)",
                (
                    task["id"],
                    datetime.now(timezone.utc).isoformat(),
                    kind,
                    json.dumps(detail if detail is not None else task),
                ),
            )

    def get(self, id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM tasks WHERE id=?", (id,)).fetchone()
        if not row:
            raise ValueError("Task not found")
        return json.loads(row[0])

    def list(self):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute("SELECT body FROM tasks ORDER BY rowid DESC")
            ]

    def audit(self, id):
        with self.connect() as db:
            return [
                dict(id=r[0], timestamp=r[1], kind=r[2], data=json.loads(r[3]))
                for r in db.execute(
                    "SELECT id,timestamp,kind,body FROM events WHERE task_id=? ORDER BY id",
                    (id,),
                )
            ]
