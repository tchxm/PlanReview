"""Subprocess runner that owns its whole process tree.

`subprocess.run(timeout=...)` kills only the direct child, so Terraform's provider plugins can
outlive a timeout. `run_tree` starts the command in its own process group/session and, on timeout
or cancellation, kills the entire tree. A job runner binds a cancel event and progress callback
for the current thread with `bind`; code that spawns Terraform needs no changes to be cancellable.
"""

import contextvars
import os
import signal
import subprocess
import time

_cancel = contextvars.ContextVar("planreview_cancel", default=None)
_progress = contextvars.ContextVar("planreview_progress", default=None)


class JobCancelled(Exception):
    """The running job was cancelled; its subprocess tree has been killed."""


def bind(cancel_event, progress_cb):
    _cancel.set(cancel_event)
    _progress.set(progress_cb)


def unbind():
    _cancel.set(None)
    _progress.set(None)


def report(text):
    cb = _progress.get()
    if cb:
        try:
            cb(text)
        except Exception:  # progress is best-effort and must never fail the operation
            pass


def kill_tree(p):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        p.kill()
    except Exception:
        pass


def run_tree(args, cwd=None, env=None, timeout=None, capture_output=True, text=True, **_ignored):
    """Drop-in for the subset of `subprocess.run` this project uses (always captures output)."""
    kw = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": text, "cwd": cwd, "env": env}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen(args, **kw)
    cancel = _cancel.get()
    deadline = time.monotonic() + timeout if timeout else None
    try:
        while True:
            try:
                out, err = p.communicate(timeout=0.5)
                return subprocess.CompletedProcess(args, p.returncode, out, err)
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    kill_tree(p)
                    p.communicate()
                    raise JobCancelled()
                if deadline is not None and time.monotonic() >= deadline:
                    kill_tree(p)
                    out, err = p.communicate()
                    raise subprocess.TimeoutExpired(args, timeout, out, err)
    except BaseException:
        if p.poll() is None:
            kill_tree(p)
        raise
