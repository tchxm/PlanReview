import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from engine.exceptions import NotFoundError

GENESIS = "0" * 64


def derive_audit_key(secret: bytes) -> bytes:
    """Domain-separated key for the audit chain (never the raw API signing secret)."""
    return hmac.new(secret, b"planreview-audit-chain-v1", hashlib.sha256).digest()


class Store:
    """SQLite task store with an append-only, keyed hash chain over the audit events.

    What the chain gives (see docs/audit-integrity.md for the exact trust model):
      * TAMPER DETECTION: editing, deleting, inserting or reordering audit rows, or
        editing the stored confirmed-contract hash, is detected by anyone who verifies
        with the key, provided the attacker did not also hold the key.
      * NOT tamper resistance and NOT protection from a compromised machine owner:
        a process running as the same OS user can read the key file and rewrite the
        database, the chain and the local anchor consistently. Only an anchor copied
        somewhere the attacker cannot write (`export_anchor`) narrows that gap.
    """

    def __init__(self, path="data/planreview.sqlite", key: bytes | None = None, anchor_path=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.key = key
        self.anchor_path = Path(anchor_path) if anchor_path else self.path.with_name("audit_anchor.json")
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, timestamp TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY, req_hash TEXT NOT NULL, task_id TEXT NOT NULL, created_at TEXT NOT NULL)")
            cols = {r[1] for r in db.execute("PRAGMA table_info(events)")}
            if "prev" not in cols:
                db.execute("ALTER TABLE events ADD COLUMN prev TEXT")
            if "mac" not in cols:
                db.execute("ALTER TABLE events ADD COLUMN mac TEXT")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        return db

    # ------------------------------------------------------------ chain
    def _mac(self, prev, id_, task_id, timestamp, kind, body):
        msg = "\x1f".join([prev, str(id_), task_id, timestamp, kind, body]).encode()
        return hmac.new(self.key, msg, hashlib.sha256).hexdigest()

    def save(self, task, kind, detail=None):
        body = json.dumps(detail if detail is not None else task)
        ts = datetime.now(timezone.utc).isoformat()
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")  # one writer at a time, across processes too
            db.execute(
                "INSERT INTO tasks VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (task["id"], json.dumps(task)),
            )
            cur = db.execute("INSERT INTO events(task_id,timestamp,kind,body) VALUES (?,?,?,?)", (task["id"], ts, kind, body))
            id_ = cur.lastrowid
            head_mac = None
            if self.key:
                last = db.execute("SELECT mac FROM events WHERE id<? AND mac IS NOT NULL ORDER BY id DESC LIMIT 1", (id_,)).fetchone()
                prev = last[0] if last else GENESIS
                head_mac = self._mac(prev, id_, task["id"], ts, kind, body)
                db.execute("UPDATE events SET prev=?, mac=? WHERE id=?", (prev, head_mac, id_))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK") if db.in_transaction else None
            raise
        finally:
            db.close()
        if self.key:
            self._write_anchor(id_, head_mac)

    # ---------------------------------------------------------- anchor
    def _write_anchor(self, head_id, head_mac):
        with self.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM events WHERE mac IS NOT NULL").fetchone()[0]
        doc = {"algo": "hmac-sha256-chain-v1", "head_id": head_id, "head_mac": head_mac, "protected_events": count, "updated_at": datetime.now(timezone.utc).isoformat()}
        fd, tmp = tempfile.mkstemp(dir=self.anchor_path.parent, prefix=".anchor-")
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f)
        os.replace(tmp, self.anchor_path)  # atomic

    def export_anchor(self, dest):
        """Copy the current anchor somewhere the database's writer cannot rewrite
        (another machine, a USB stick, a read-only share). Returns the anchor document."""
        doc = json.loads(Path(self.anchor_path).read_text())
        Path(dest).write_text(json.dumps(doc))
        return doc

    # ---------------------------------------------------------- verify
    def verify_audit(self, anchor_path=None):
        """Recompute the chain. Returns {ok, checked, problems[], unprotected_legacy_events}."""
        problems, checked, legacy = [], 0, 0
        if not self.key:
            return {"ok": False, "checked": 0, "problems": [{"type": "NO_KEY", "detail": "no audit key configured"}], "unprotected_legacy_events": 0}
        with self.connect() as db:
            rows = db.execute("SELECT id,task_id,timestamp,kind,body,prev,mac FROM events ORDER BY id").fetchall()
            tasks = {r[0]: json.loads(r[1]) for r in db.execute("SELECT id, body FROM tasks")}
        prev_mac, last_id, seen_protected = GENESIS, None, False
        for id_, task_id, ts, kind, body, prev, mac in rows:
            if mac is None:
                if seen_protected:
                    problems.append({"type": "UNPROTECTED_ROW_AFTER_CHAIN_START", "event_id": id_})
                legacy += 1
                continue
            seen_protected = True
            checked += 1
            if last_id is not None and id_ != last_id + 1:
                problems.append({"type": "GAP_OR_DELETION", "event_id": id_, "after": last_id})
            if prev != prev_mac:
                problems.append({"type": "CHAIN_BROKEN", "event_id": id_})
            if not hmac.compare_digest(mac, self._mac(prev, id_, task_id, ts, kind, body)):
                problems.append({"type": "ROW_MODIFIED", "event_id": id_})
            prev_mac, last_id = mac, id_
        # the tasks table must agree with the protected confirmation record
        confirmations = {}
        for id_, task_id, ts, kind, body, prev, mac in rows:
            if kind == "human_confirmation" and mac is not None:
                confirmations[task_id] = json.loads(body).get("confirmed_contract_hash")
        for task_id, expected in confirmations.items():
            t = tasks.get(task_id)
            if t is None:
                problems.append({"type": "TASK_ROW_DELETED", "task_id": task_id})
            elif t.get("confirmed_contract_hash") != expected:
                problems.append({"type": "CONFIRMED_CONTRACT_HASH_DIFFERS_FROM_AUDIT", "task_id": task_id})
        # the anchor catches tail truncation and wholesale replacement
        ap = Path(anchor_path) if anchor_path else self.anchor_path
        if ap.exists():
            a = json.loads(ap.read_text())
            if a.get("head_id") is not None:
                head = next((r for r in rows if r[0] == a["head_id"]), None)
                if head is None or head[6] != a["head_mac"]:
                    problems.append({"type": "ANCHOR_MISMATCH", "detail": "head recorded in the anchor is missing or different (tail removed or database replaced)"})
                elif last_id is not None and last_id > a["head_id"]:
                    pass  # newer than the anchor copy is fine for an exported (older) anchor
        elif checked:
            problems.append({"type": "ANCHOR_MISSING", "detail": "no anchor file to compare against"})
        return {"ok": not problems, "checked": checked, "problems": problems, "unprotected_legacy_events": legacy}

    # ------------------------------------------------------ idempotency
    def idem_get(self, key):
        with self.connect() as db:
            r = db.execute("SELECT req_hash, task_id FROM idempotency WHERE key=?", (key,)).fetchone()
        return {"req_hash": r[0], "task_id": r[1]} if r else None

    def idem_put(self, key, req_hash, task_id):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO idempotency VALUES (?,?,?,?)", (key, req_hash, task_id, datetime.now(timezone.utc).isoformat()))

    # ------------------------------------------------------------ reads
    def get(self, id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM tasks WHERE id=?", (id,)).fetchone()
        if not row:
            raise NotFoundError("Task not found")
        return json.loads(row[0])

    def list(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM tasks ORDER BY rowid DESC")]

    def audit(self, id):
        with self.connect() as db:
            return [
                dict(id=r[0], timestamp=r[1], kind=r[2], data=json.loads(r[3]))
                for r in db.execute("SELECT id,timestamp,kind,body FROM events WHERE task_id=? ORDER BY id", (id,))
            ]
