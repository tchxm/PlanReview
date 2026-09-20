"""Deliberate tampering against the audit hash chain, using raw SQLite to play the attacker.
Claims are limited to DETECTION by someone without the key; see docs/audit-integrity.md."""

import json
import shutil
import sqlite3

import pytest

from engine import auth
from engine.pipeline import Pipeline
from engine.storage import Store, derive_audit_key
from tests.conftest import SECRET


@pytest.fixture
def pipe(tmp_path):
    p = Pipeline(tmp_path)
    t = p.create("Increase memory for dev-api Lambda")
    p.confirm(t["id"], t["contract"])
    p.agent(t["id"], "intended")
    return p, t["id"], tmp_path / "planreview.sqlite"


def raw(path, sql, *args):
    db = sqlite3.connect(path)
    try:
        cur = db.execute(sql, args)
        db.commit()
        return cur.fetchall()
    finally:
        db.close()


def types(result):
    return {p["type"] for p in result["problems"]}


def test_untouched_chain_verifies(pipe):
    p, tid, db = pipe
    r = p.store.verify_audit()
    assert r["ok"] and r["checked"] == 3 and r["problems"] == []


def test_new_events_extend_the_chain(pipe):
    p, tid, db = pipe
    before = p.store.verify_audit()["checked"]
    p.plan(tid)
    r = p.store.verify_audit()
    assert r["ok"] and r["checked"] == before + 1


def test_modified_event_is_detected(pipe):
    p, tid, db = pipe
    raw(db, "UPDATE events SET body = replace(body, 'intended', 'poisoned') WHERE kind='agent_edits'")
    r = p.store.verify_audit()
    assert not r["ok"] and "ROW_MODIFIED" in types(r)


def test_modified_timestamp_or_kind_is_detected(pipe):
    p, tid, db = pipe
    raw(db, "UPDATE events SET kind='draft' WHERE kind='agent_edits'")
    assert "ROW_MODIFIED" in types(p.store.verify_audit())


def test_deleted_middle_event_is_detected(pipe):
    p, tid, db = pipe
    raw(db, "DELETE FROM events WHERE kind='human_confirmation'")
    r = p.store.verify_audit()
    assert not r["ok"] and {"GAP_OR_DELETION", "CHAIN_BROKEN"} & types(r)


def test_reordered_events_are_detected(pipe):
    p, tid, db = pipe
    rows = raw(db, "SELECT id FROM events ORDER BY id")
    a, b = rows[0][0], rows[1][0]
    raw(db, "UPDATE events SET id=-1 WHERE id=?", a)
    raw(db, "UPDATE events SET id=? WHERE id=?", a, b)
    raw(db, "UPDATE events SET id=? WHERE id=-1", b)
    r = p.store.verify_audit()
    assert not r["ok"] and {"CHAIN_BROKEN", "ROW_MODIFIED"} & types(r)


def test_inserted_forged_event_is_detected(pipe):
    p, tid, db = pipe
    raw(db, "INSERT INTO events(task_id,timestamp,kind,body,prev,mac) VALUES (?,?,?,?,?,?)", tid, "2026-01-01T00:00:00+00:00", "human_resolution", json.dumps({"forged": True}), "0" * 64, "f" * 64)
    r = p.store.verify_audit()
    assert not r["ok"] and {"ROW_MODIFIED", "CHAIN_BROKEN"} & types(r)


def test_truncated_tail_is_detected_by_the_anchor(pipe):
    p, tid, db = pipe
    raw(db, "DELETE FROM events WHERE id=(SELECT MAX(id) FROM events)")
    r = p.store.verify_audit()
    assert not r["ok"] and "ANCHOR_MISMATCH" in types(r)


def test_rewriting_the_confirmed_contract_and_its_hash_in_the_tasks_table_is_detected(pipe):
    """The unkeyed contract digest alone can be recomputed by a DB writer; the keyed audit record cannot."""
    from engine.pipeline import contract_digest

    p, tid, db = pipe
    body = json.loads(raw(db, "SELECT body FROM tasks WHERE id=?", tid)[0][0])
    body["contract"]["max_changed_resources"] = 99
    body["confirmed_contract_hash"] = contract_digest(body["contract"])  # attacker recomputes the digest
    raw(db, "UPDATE tasks SET body=? WHERE id=?", json.dumps(body), tid)
    p.store.get(tid)  # the pipeline's own digest check would now PASS...
    r = p.store.verify_audit()  # ...but the keyed audit cross-check does not
    assert not r["ok"] and "CONFIRMED_CONTRACT_HASH_DIFFERS_FROM_AUDIT" in types(r)


def test_deleting_the_task_row_is_detected(pipe):
    p, tid, db = pipe
    raw(db, "DELETE FROM tasks WHERE id=?", tid)
    assert "TASK_ROW_DELETED" in types(p.store.verify_audit())


def test_wrong_key_cannot_verify(pipe):
    p, tid, db = pipe
    other = Store(db, key=derive_audit_key(b"another secret " + b"z" * 32))
    r = other.verify_audit()
    assert not r["ok"] and "ROW_MODIFIED" in types(r)


def test_attacker_WITH_the_key_can_rewrite_everything_local_anchor_included(pipe, tmp_path):
    """Honest limit: same-OS-user compromise defeats local detection. An exported anchor still catches it."""
    p, tid, db = pipe
    exported = tmp_path / "offbox_anchor.json"
    p.store.export_anchor(exported)
    # the attacker holds the key: rebuild a self-consistent chain without the last two events
    raw(db, "DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id DESC LIMIT 2)")
    raw(db, "UPDATE sqlite_sequence SET seq=(SELECT MAX(id) FROM events) WHERE name='events'")  # hide the id gap
    forged = Store(db, key=derive_audit_key(SECRET))
    forged.save({"id": tid}, "human_resolution", {"forged": True})  # extends a valid chain and re-writes the LOCAL anchor
    local = forged.verify_audit()
    assert local["ok"], "with the key, local verification is fooled (this is the documented limit)"
    external = forged.verify_audit(anchor_path=exported)
    assert not external["ok"] and "ANCHOR_MISMATCH" in types(external)


def test_legacy_rows_without_macs_are_reported_not_trusted(tmp_path):
    db = tmp_path / "planreview.sqlite"
    plain = Store(db)  # no key: legacy behaviour, rows carry no MAC
    plain.save({"id": "t1"}, "draft", {"x": 1})
    keyed = Store(db, key=derive_audit_key(SECRET))
    keyed.save({"id": "t2"}, "draft", {"y": 2})
    r = keyed.verify_audit()
    assert r["unprotected_legacy_events"] == 1 and r["checked"] == 1 and r["ok"]


def test_verify_endpoint_requires_evidence_scope_and_reports_tampering(pipe, monkeypatch):
    from fastapi.testclient import TestClient

    from engine import api
    from tests.conftest import token

    p, tid, db = pipe
    monkeypatch.setattr(api, "pipeline", p)
    c = TestClient(api.app)
    assert c.get("/api/audit/verify").json()["ok"] is True
    raw(db, "UPDATE events SET body='{}' WHERE kind='human_confirmation'")
    assert c.get("/api/audit/verify").json()["ok"] is False
    r = TestClient(api.app, headers={}).get("/api/audit/verify", headers={"Authorization": "Bearer " + token(["read", "write"])})
    assert r.status_code == 403


def test_concurrent_writers_keep_a_valid_chain(tmp_path):
    import threading

    p = Pipeline(tmp_path)
    ids = [p.create("Increase memory for dev-api Lambda")["id"] for _ in range(6)]
    ts = [threading.Thread(target=lambda i=i: [p.store.save({"id": i}, "note", {"n": k}) for k in range(15)]) for i in ids]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    r = p.store.verify_audit()
    assert r["ok"], r["problems"][:3]
    assert r["checked"] == 6 + 6 * 15
