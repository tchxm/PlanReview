import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import time
import uuid

from engine.exceptions import NotFoundError, StateConflictError

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

    def __init__(self, path="data/planreview.sqlite", key: bytes | None = None, anchor_path=None, vault=None, mirror_path=None):
        self.vault = vault
        m = mirror_path or os.environ.get("PLANREVIEW_AUDIT_MIRROR")
        self.mirror_path = Path(m) if m else None
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
            db.execute("CREATE TABLE IF NOT EXISTS revoked_tokens (jti TEXT PRIMARY KEY, revoked_at TEXT NOT NULL, revoked_by TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, op TEXT NOT NULL, args TEXT NOT NULL, actor TEXT, "
                "status TEXT NOT NULL, progress TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, heartbeat_at TEXT, worker TEXT, "
                "cancel_requested INTEGER NOT NULL DEFAULT 0, error_code TEXT, error_message TEXT, result TEXT)"
            )
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_job_per_task ON jobs(task_id) WHERE status IN ('queued','running')")
            icols = {r[1] for r in db.execute("PRAGMA table_info(idempotency)")}
            if "response" not in icols:
                db.execute("ALTER TABLE idempotency ADD COLUMN response TEXT")
            tcols = {r[1] for r in db.execute("PRAGMA table_info(tasks)")}
            if "version" not in tcols:
                db.execute("ALTER TABLE tasks ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
            cols = {r[1] for r in db.execute("PRAGMA table_info(events)")}
            if "prev" not in cols:
                db.execute("ALTER TABLE events ADD COLUMN prev TEXT")
            if "mac" not in cols:
                db.execute("ALTER TABLE events ADD COLUMN mac TEXT")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        return db

    # ------------------------------------------------------- revocation
    def revoke(self, jti, by):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO revoked_tokens VALUES (?,?,?)", (jti, datetime.now(timezone.utc).isoformat(), by))

    def is_revoked(self, jti):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM revoked_tokens WHERE jti=?", (jti,)).fetchone() is not None

    # ------------------------------------------------------------ chain
    def _mac(self, prev, id_, task_id, timestamp, kind, body):
        msg = "\x1f".join([prev, str(id_), task_id, timestamp, kind, body]).encode()
        return hmac.new(self.key, msg, hashlib.sha256).hexdigest()

    def save(self, task, kind, detail=None):
        """Persist a task and append its audit event atomically.

        Optimistic concurrency: a task read with `get` carries `_version`. Saving it succeeds only if
        nobody else saved the task since (in ANY process); otherwise CONCURRENT_MODIFICATION (409) and
        nothing is written. A task dict without `_version` (a brand-new task) is written unconditionally."""
        clean = {k: v for k, v in task.items() if k != "_version"}
        expected = task.get("_version")
        if self.vault is not None and self.vault.enabled and isinstance(detail, dict) and detail.get("raw_plan") is not None:
            detail = {**detail, "raw_plan": None, "raw_plan_enc": self.vault.encrypt_text(json.dumps(detail["raw_plan"]))}
        body = json.dumps(detail if detail is not None else clean)
        ts = datetime.now(timezone.utc).isoformat()
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")  # one writer at a time, across processes too
            if expected is None:
                db.execute(
                    "INSERT INTO tasks(id,body,version) VALUES (?,?,1) ON CONFLICT(id) DO UPDATE SET body=excluded.body, version=version+1",
                    (clean["id"], json.dumps(clean)),
                )
                new_version = db.execute("SELECT version FROM tasks WHERE id=?", (clean["id"],)).fetchone()[0]
            else:
                cur = db.execute("UPDATE tasks SET body=?, version=version+1 WHERE id=? AND version=?", (json.dumps(clean), clean["id"], expected))
                if cur.rowcount != 1:
                    raise StateConflictError(
                        "The task was changed by another request; reload it and retry", code="CONCURRENT_MODIFICATION"
                    )
                new_version = expected + 1
            cur = db.execute("INSERT INTO events(task_id,timestamp,kind,body) VALUES (?,?,?,?)", (clean["id"], ts, kind, body))
            id_ = cur.lastrowid
            head_mac = None
            if self.key:
                last = db.execute("SELECT mac FROM events WHERE id<? AND mac IS NOT NULL ORDER BY id DESC LIMIT 1", (id_,)).fetchone()
                prev = last[0] if last else GENESIS
                head_mac = self._mac(prev, id_, clean["id"], ts, kind, body)
                db.execute("UPDATE events SET prev=?, mac=? WHERE id=?", (prev, head_mac, id_))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK") if db.in_transaction else None
            raise
        finally:
            db.close()
        task["_version"] = new_version
        if self.key:
            self._write_anchor(id_, head_mac)
            if self.mirror_path:
                self._append_mirror(id_, head_mac)

    # ---------------------------------------------------------- anchor
    def _write_anchor(self, head_id, head_mac):
        with self.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM events WHERE mac IS NOT NULL").fetchone()[0]
        doc = {"algo": "hmac-sha256-chain-v1", "head_id": head_id, "head_mac": head_mac, "protected_events": count, "updated_at": datetime.now(timezone.utc).isoformat()}
        fd, tmp = tempfile.mkstemp(dir=self.anchor_path.parent, prefix=".anchor-")
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f)
        for attempt in range(20):  # Windows can refuse a replace while a concurrent writer holds the target
            try:
                os.replace(tmp, self.anchor_path)  # atomic
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.01 * (attempt + 1))

    def _append_mirror(self, head_id, head_mac):
        """Append-only witness of every chain head, meant to live where the database's writer cannot rewrite it
        (another disk, a network share, a synced folder, a WORM bucket mount). A same-user attacker who rewrites the
        database, the chain AND the local anchor still cannot change lines already in the mirror."""
        try:
            self.mirror_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.mirror_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"head_id": head_id, "head_mac": head_mac, "at": datetime.now(timezone.utc).isoformat()}) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            import logging

            logging.getLogger("planreview").error("audit mirror is not writable: %s", self.mirror_path)

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
        if self.mirror_path and self.mirror_path.exists():
            by_id = {r[0]: r[6] for r in rows}
            for n, line in enumerate(self.mirror_path.read_text(encoding="utf-8").splitlines(), 1):
                try:
                    m = json.loads(line)
                except ValueError:
                    problems.append({"type": "MIRROR_CORRUPT", "line": n})
                    continue
                if m.get("head_id") not in by_id or by_id[m["head_id"]] != m.get("head_mac"):
                    problems.append({"type": "MIRROR_MISMATCH", "line": n, "detail": "a chain head recorded in the external mirror is missing or different"})
        elif self.mirror_path and checked:
            problems.append({"type": "MIRROR_MISSING", "detail": "an audit mirror is configured but has no entries"})
        return {"ok": not problems, "checked": checked, "problems": problems, "unprotected_legacy_events": legacy}

    # ------------------------------------------------------ idempotency
    def idem_get(self, key):
        with self.connect() as db:
            r = db.execute("SELECT req_hash, task_id, response FROM idempotency WHERE key=?", (key,)).fetchone()
        return {"req_hash": r[0], "task_id": r[1], "response": r[2]} if r else None

    def idem_put(self, key, req_hash, task_id, response=None):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO idempotency(key,req_hash,task_id,created_at,response) VALUES (?,?,?,?,?)",
                (key, req_hash, task_id, datetime.now(timezone.utc).isoformat(), response),
            )

    # ------------------------------------------------------------ reads
    def get(self, id):
        with self.connect() as db:
            row = db.execute("SELECT body, version FROM tasks WHERE id=?", (id,)).fetchone()
        if not row:
            raise NotFoundError("Task not found")
        return {**json.loads(row[0]), "_version": row[1]}

    def list(self, limit=None, offset=0):
        sql, args = "SELECT body, version FROM tasks ORDER BY rowid DESC", ()
        if limit is not None:
            sql, args = sql + " LIMIT ? OFFSET ?", (limit, offset)
        with self.connect() as db:
            return [{**json.loads(r[0]), "_version": r[1]} for r in db.execute(sql, args)]

    def count(self):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    def audit_count(self, id):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM events WHERE task_id=?", (id,)).fetchone()[0]

    def audit(self, id, limit=None, offset=0):
        sql, args = "SELECT id,timestamp,kind,body FROM events WHERE task_id=? ORDER BY id", (id,)
        if limit is not None:
            sql, args = sql + " LIMIT ? OFFSET ?", (id, limit, offset)
        with self.connect() as db:
            rows = [dict(id=r[0], timestamp=r[1], kind=r[2], data=json.loads(r[3])) for r in db.execute(sql, args)]
        for r in rows:  # the chain MACs the sealed form; callers get the original evidence back
            d = r["data"]
            if isinstance(d, dict) and d.get("raw_plan_enc") and self.vault is not None and self.vault.enabled:
                d["raw_plan"] = json.loads(self.vault.decrypt_text(d.pop("raw_plan_enc")))
        return rows

    # ------------------------------------------------------------- jobs
    JOB_COLS = "id,task_id,op,args,actor,status,progress,created_at,started_at,finished_at,heartbeat_at,worker,cancel_requested,error_code,error_message,result"

    @staticmethod
    def _job(r):
        if r is None:
            return None
        j = dict(zip(Store.JOB_COLS.split(","), r))
        j["args"] = json.loads(j["args"])
        j["result"] = json.loads(j["result"]) if j["result"] else None
        j["cancel_requested"] = bool(j["cancel_requested"])
        return j

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def job_create(self, task_id, op, args, actor):
        jid = uuid.uuid4().hex
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO jobs(id,task_id,op,args,actor,status,created_at) VALUES (?,?,?,?,?,'queued',?)",
                    (jid, task_id, op, json.dumps(args), actor, self._now()),
                )
        except sqlite3.IntegrityError:
            active = self.job_active(task_id)
            raise StateConflictError(
                "A job is already active for this task", code="JOB_IN_PROGRESS", details={"job_id": active["id"] if active else None}
            )
        return self.job_get(jid)

    def job_get(self, jid):
        with self.connect() as db:
            return self._job(db.execute(f"SELECT {self.JOB_COLS} FROM jobs WHERE id=?", (jid,)).fetchone())

    def job_active(self, task_id):
        with self.connect() as db:
            return self._job(db.execute(f"SELECT {self.JOB_COLS} FROM jobs WHERE task_id=? AND status IN ('queued','running')", (task_id,)).fetchone())

    def jobs_for_task(self, task_id):
        with self.connect() as db:
            return [self._job(r) for r in db.execute(f"SELECT {self.JOB_COLS} FROM jobs WHERE task_id=? ORDER BY created_at DESC", (task_id,))]

    def job_claim(self, worker):
        """Atomically take the oldest queued job (safe with several workers/processes)."""
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            r = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not r:
                db.execute("COMMIT")
                return None
            now = self._now()
            db.execute("UPDATE jobs SET status='running', worker=?, started_at=?, heartbeat_at=?, progress='starting' WHERE id=?", (worker, now, now, r[0]))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK") if db.in_transaction else None
            raise
        finally:
            db.close()
        return self.job_get(r[0])

    def job_progress(self, jid, text):
        with self.connect() as db:
            db.execute("UPDATE jobs SET progress=? WHERE id=? AND status='running'", (str(text)[:200], jid))

    def job_heartbeat(self, ids):
        if ids:
            with self.connect() as db:
                db.executemany("UPDATE jobs SET heartbeat_at=? WHERE id=? AND status='running'", [(self._now(), i) for i in ids])

    def job_cancel_requested(self, ids):
        if not ids:
            return set()
        with self.connect() as db:
            q = ",".join("?" * len(ids))
            return {r[0] for r in db.execute(f"SELECT id FROM jobs WHERE cancel_requested=1 AND status='running' AND id IN ({q})", list(ids))}

    def job_finish(self, jid, status, error_code=None, error_message=None, result=None):
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET status=?, finished_at=?, error_code=?, error_message=?, result=? WHERE id=? AND status IN ('queued','running')",
                (status, self._now(), error_code, error_message, json.dumps(result) if result is not None else None, jid),
            )

    def job_cancel(self, jid):
        """Queued jobs cancel immediately; running jobs are flagged and their owner kills the work."""
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='cancelled', finished_at=? WHERE id=? AND status='queued'", (self._now(), jid))
            db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=? AND status='running'", (jid,))
        return self.job_get(jid)

    def job_recover(self, stale_seconds):
        """Running jobs whose worker stopped heartbeating (crash, kill, restart) become `interrupted`.
        Task state is untouched: a task is only saved when an operation completes."""
        cutoff = datetime.fromtimestamp(time.time() - stale_seconds, timezone.utc).isoformat()
        with self.connect() as db:
            cur = db.execute(
                "UPDATE jobs SET status='interrupted', finished_at=?, error_code='JOB_INTERRUPTED', "
                "error_message='The worker stopped before the job finished; resubmit it' WHERE status='running' AND heartbeat_at < ?",
                (self._now(), cutoff),
            )
            return cur.rowcount
