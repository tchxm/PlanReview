"""Durable background jobs.

A job is a row in SQLite, so it survives a client disconnect and a server restart:
  queued -> running -> succeeded | failed | cancelled | interrupted

* Submitting returns immediately (HTTP 202); clients poll `GET /api/jobs/{id}` for status and progress.
* At most ONE queued/running job per task (unique index), so long operations never interleave.
* Workers claim jobs atomically; a heartbeat every second proves the worker is alive. A running job
  whose heartbeat goes stale (crash, kill -9, restart) is marked `interrupted` and can be resubmitted.
  Task state is only written when an operation completes, so an interrupted job leaves it consistent.
* Cancelling kills the Terraform process TREE (see engine/proc.py), not just the direct child.
* Multiple API processes may share one database: claiming, heartbeats and cancel flags all live in it.
"""

import logging
import os
import subprocess
import threading
import uuid

from engine import proc
from engine.exceptions import InvalidRequestError, NotFoundError, PlanReviewError
from engine.sanitize import scrub

log = logging.getLogger("planreview")

OPS = {"agent", "plan", "apply"}


class JobRunner:
    def __init__(self, pipeline, workers=None, stale_seconds=15, poll=0.5, heartbeat=1.0):
        self.pipeline = pipeline
        self.store = pipeline.store
        self.workers = workers or int(os.environ.get("PLANREVIEW_JOB_WORKERS", "2"))
        self.stale, self.poll, self.heartbeat = stale_seconds, poll, heartbeat
        self._stop = threading.Event()
        self._threads = []
        self._events = {}
        self._guard = threading.Lock()
        self.id = uuid.uuid4().hex[:8]

    # --------------------------------------------------------- lifecycle
    def start(self):
        if self._threads:
            return
        self.store.job_recover(self.stale)
        for i in range(self.workers):
            self._threads.append(threading.Thread(target=self._work, args=(f"{self.id}-{i}",), daemon=True, name=f"planreview-job-{i}"))
        self._threads.append(threading.Thread(target=self._beat, daemon=True, name="planreview-job-heartbeat"))
        for t in self._threads:
            t.start()

    def stop(self):
        self._stop.set()

    # -------------------------------------------------------- submission
    def submit(self, task_id, op, args, actor):
        if op not in OPS:
            raise InvalidRequestError(f"op must be one of {sorted(OPS)}", code="INVALID_JOB_OP")
        self.store.get(task_id)  # 404 for an unknown task
        return self.store.job_create(task_id, op, args or {}, actor)

    def cancel(self, job_id):
        if self.store.job_get(job_id) is None:
            raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
        return self.store.job_cancel(job_id)

    # ----------------------------------------------------------- workers
    def _beat(self):
        n = 0
        while not self._stop.wait(self.heartbeat):
            try:
                with self._guard:
                    ids = list(self._events)
                self.store.job_heartbeat(ids)
                for jid in self.store.job_cancel_requested(ids):
                    ev = self._events.get(jid)
                    if ev:
                        ev.set()
                n += 1
                if n % 5 == 0:
                    self.store.job_recover(self.stale)
            except Exception:
                log.exception("job heartbeat failed")

    def _work(self, worker):
        while not self._stop.is_set():
            try:
                job = self.store.job_claim(worker)
            except Exception:
                log.exception("job claim failed")
                job = None
            if job is None:
                self._stop.wait(self.poll)
                continue
            self._execute(job)

    def _execute(self, job):
        from engine.pipeline import LOCKS

        cancel = threading.Event()
        with self._guard:
            self._events[job["id"]] = cancel
        proc.bind(cancel, lambda text: self.store.job_progress(job["id"], text))
        try:
            with LOCKS.get(job["task_id"]):
                if cancel.is_set() or (self.store.job_get(job["id"]) or {}).get("cancel_requested"):
                    raise proc.JobCancelled()
                fn = getattr(self.pipeline, job["op"])
                if job["op"] == "agent":
                    task = fn(job["task_id"], job["args"].get("variant", "poisoned"))
                elif job["op"] == "apply":
                    task = fn(job["task_id"], job["actor"])
                else:
                    task = fn(job["task_id"])
            self.store.job_finish(job["id"], "succeeded", result={"stage": task.get("stage")})
        except proc.JobCancelled:
            self.store.job_finish(job["id"], "cancelled", error_code="JOB_CANCELLED", error_message="Cancelled by request")
        except PlanReviewError as exc:
            self.store.job_finish(job["id"], "failed", error_code=exc.code, error_message=scrub(exc.message))
        except subprocess.TimeoutExpired:
            self.store.job_finish(job["id"], "failed", error_code="TERRAFORM_TIMEOUT", error_message="Terraform timed out")
        except Exception:
            log.exception("job %s (%s) crashed", job["id"], job["op"])
            self.store.job_finish(job["id"], "failed", error_code="INTERNAL_ERROR", error_message="An internal error occurred; see the server log")
        finally:
            proc.unbind()
            with self._guard:
                self._events.pop(job["id"], None)
