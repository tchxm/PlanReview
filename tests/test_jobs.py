"""Cross-process task safety (optimistic versions) and durable background jobs."""

import multiprocessing
import os
import subprocess
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from engine import api, proc
from engine.exceptions import StateConflictError
from engine.jobs import JobRunner
from engine.pipeline import Pipeline
from engine.storage import Store
from tests.conftest import token


def new_task(store, **extra):
    t = {"id": "t1", "n": 0, "stage": "draft", "runs": [], **extra}
    store.save(t, "draft")
    return store.get("t1")


# ---------------------------------------------------------------- versions
def test_stale_save_is_rejected_and_writes_nothing(tmp_path):
    s = Store(tmp_path / "db.sqlite", key=b"k" * 32)
    a, b = new_task(s), s.get("t1")
    a["n"] = 1
    s.save(a, "x")
    b["n"] = 99
    with pytest.raises(StateConflictError) as e:
        s.save(b, "x")
    assert e.value.code == "CONCURRENT_MODIFICATION"
    assert s.get("t1")["n"] == 1
    assert [ev["kind"] for ev in s.audit("t1")] == ["draft", "x"]  # the rejected save left no audit event
    assert s.verify_audit()["ok"]


def test_version_never_leaks_into_storage_or_audit(tmp_path):
    s = Store(tmp_path / "db.sqlite", key=b"k" * 32)
    t = new_task(s)
    assert t["_version"] >= 1
    assert all("_version" not in ev["data"] for ev in s.audit("t1"))


def _hammer(path, n, done):
    s = Store(path, key=b"k" * 32)
    ok = 0
    while ok < n:
        t = s.get("t1")
        t["n"] += 1
        try:
            s.save(t, "inc")
            ok += 1
        except StateConflictError:
            pass
    done.put(ok)


def test_lost_updates_are_impossible_across_processes(tmp_path):
    path = tmp_path / "db.sqlite"
    s = Store(path, key=b"k" * 32)
    new_task(s)
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_hammer, args=(str(path), 15, q)) for _ in range(3)]
    [p.start() for p in procs]
    [p.join(120) for p in procs]
    assert all(p.exitcode == 0 for p in procs)
    assert s.get("t1")["n"] == 45  # every increment from every process survived
    assert s.verify_audit()["ok"]


# ------------------------------------------------------------- process tree
def _spawn_grandchild_cmd(pidfile):
    code = (
        "import subprocess,sys,time;"
        f"c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"open(r'{pidfile}','w').write(str(c.pid));time.sleep(60)"
    )
    return [sys.executable, "-c", code]


def _alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _wait_pid(pidfile):
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text():
            return int(pidfile.read_text())
        time.sleep(0.1)
    raise AssertionError("grandchild never started")


def test_timeout_kills_the_whole_process_tree(tmp_path):
    pidfile = tmp_path / "pid"
    with pytest.raises(subprocess.TimeoutExpired):
        proc.run_tree(_spawn_grandchild_cmd(pidfile), timeout=3)
    time.sleep(1)
    assert not _alive(_wait_pid(pidfile))


def test_cancel_kills_the_whole_process_tree(tmp_path):
    pidfile, ev = tmp_path / "pid", threading.Event()
    result = {}

    def run():
        proc.bind(ev, None)
        try:
            proc.run_tree(_spawn_grandchild_cmd(pidfile), timeout=60)
        except proc.JobCancelled:
            result["cancelled"] = True

    th = threading.Thread(target=run)
    th.start()
    pid = _wait_pid(pidfile)
    ev.set()
    th.join(20)
    assert result.get("cancelled")
    time.sleep(1)
    assert not _alive(pid)


# --------------------------------------------------------------------- jobs
@pytest.fixture
def env(tmp_path, monkeypatch):
    p = Pipeline(tmp_path)
    monkeypatch.setattr(api, "pipeline", p)
    api._runner_state.clear()
    client = TestClient(api.app)
    yield p, client
    if api._runner_state.get("r"):
        api._runner_state["r"].stop()
    api._runner_state.clear()


def wait_for(client, job_id, want, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in want:
            return j
        time.sleep(0.2)
    raise AssertionError(f"job stuck: {j}")


def make_task(client):
    return client.post("/api/tasks", json={"task": "Increase dev-api Lambda memory to 1024 MB"}).json()["id"]


def test_job_runs_in_background_and_reports_result(env):
    p, client = env
    tid = make_task(client)
    p.plan = lambda id: (proc.report("terraform plan"), {"stage": "planned"})[1]
    r = client.post(f"/api/tasks/{tid}/jobs", json={"op": "plan"})
    assert r.status_code == 202 and r.json()["status"] in ("queued", "running")
    j = wait_for(client, r.json()["id"], {"succeeded"})
    assert j["result"] == {"stage": "planned"} and j["requested_by"] == "local"
    assert [x["id"] for x in client.get(f"/api/tasks/{tid}/jobs").json()] == [j["id"]]


def test_failed_job_reports_a_stable_error_code(env):
    p, client = env
    tid = make_task(client)
    j = client.post(f"/api/tasks/{tid}/jobs", json={"op": "agent", "variant": "nope"}).json()
    j = wait_for(client, j["id"], {"failed"})
    assert j["error"]["code"] == "CONTRACT_NOT_ACTIVE" or j["error"]["code"] == "UNKNOWN_FIXTURE"


def test_only_one_active_job_per_task_and_sync_endpoints_yield(env):
    p, client = env
    tid = make_task(client)
    gate = threading.Event()
    p.plan = lambda id: gate.wait(20) and {"stage": "planned"}
    j1 = client.post(f"/api/tasks/{tid}/jobs", json={"op": "plan"}).json()
    r = client.post(f"/api/tasks/{tid}/jobs", json={"op": "plan"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "JOB_IN_PROGRESS"
    r = client.post(f"/api/tasks/{tid}/confirm", json={})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "JOB_IN_PROGRESS"
    assert client.get(f"/api/tasks/{tid}").status_code == 200  # reads are never blocked
    gate.set()
    wait_for(client, j1["id"], {"succeeded"})
    assert client.post(f"/api/tasks/{tid}/confirm", json={}).status_code == 200


def test_cancel_running_job(env):
    p, client = env
    tid = make_task(client)

    def slow(id):
        proc.run_tree([sys.executable, "-c", "import time;time.sleep(60)"], timeout=60)

    p.plan = slow
    j = client.post(f"/api/tasks/{tid}/jobs", json={"op": "plan"}).json()
    wait_for(client, j["id"], {"running"})
    assert client.post(f"/api/jobs/{j['id']}/cancel").json()["cancel_requested"] is True
    j = wait_for(client, j["id"], {"cancelled"}, timeout=20)
    assert j["error"]["code"] == "JOB_CANCELLED"


def test_cancel_queued_job_is_immediate(tmp_path):
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory to 1024 MB")
    runner = JobRunner(p)  # deliberately not started: the job stays queued
    j = runner.submit(t["id"], "plan", {}, "alice")
    assert runner.cancel(j["id"])["status"] == "cancelled"
    assert p.store.job_active(t["id"]) is None


def test_dead_worker_job_becomes_interrupted_then_can_be_resubmitted(tmp_path):
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory to 1024 MB")
    runner = JobRunner(p)
    j = runner.submit(t["id"], "plan", {}, "alice")
    assert p.store.job_claim("worker-that-dies")["id"] == j["id"]  # worker "crashes" right here: no heartbeat, no finish
    assert p.store.job_recover(stale_seconds=3600) == 0  # a fresh heartbeat is not stale
    time.sleep(1.2)
    assert p.store.job_recover(stale_seconds=1) == 1
    j = p.store.job_get(j["id"])
    assert j["status"] == "interrupted" and j["error_code"] == "JOB_INTERRUPTED"
    assert runner.submit(t["id"], "plan", {}, "alice")["status"] == "queued"


def test_queued_job_survives_restart_and_runs(tmp_path):
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory to 1024 MB")
    JobRunner(p).submit(t["id"], "plan", {}, "alice")  # "server" dies before any worker runs it
    p2 = Pipeline(tmp_path)  # restart
    p2.plan = lambda id: {"stage": "planned"}
    r = JobRunner(p2)
    r.start()
    try:
        end = time.time() + 20
        while time.time() < end and p2.store.jobs_for_task(t["id"])[0]["status"] != "succeeded":
            time.sleep(0.2)
        assert p2.store.jobs_for_task(t["id"])[0]["status"] == "succeeded"
    finally:
        r.stop()


def test_bad_op_and_unknown_ids(env):
    p, client = env
    tid = make_task(client)
    assert client.post(f"/api/tasks/{tid}/jobs", json={"op": "rm -rf"}).status_code == 422
    assert client.post("/api/tasks/nope/jobs", json={"op": "plan"}).status_code == 404
    assert client.get("/api/jobs/nope").json()["detail"]["error"] == "JOB_NOT_FOUND"
    assert client.post("/api/jobs/nope/cancel").json()["detail"]["error"] == "JOB_NOT_FOUND"


def test_job_endpoints_require_the_right_scope(env):
    p, client = env
    tid = make_task(client)
    ro = {"Authorization": "Bearer " + token(["read"])}
    anon = TestClient(api.app, headers={})
    assert anon.get("/api/jobs/x").status_code == 401
    assert client.post(f"/api/tasks/{tid}/jobs", json={"op": "plan"}, headers=ro).status_code == 403
    assert client.post("/api/jobs/x/cancel", headers=ro).status_code == 403
    assert client.get(f"/api/tasks/{tid}/jobs", headers=ro).status_code == 200
