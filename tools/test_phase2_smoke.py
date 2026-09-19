"""Separate-process smoke test: FastAPI (8000) + Vite (5173) + /api proxy.

Run from the repo root with the ports free:  python tools/test_phase2_smoke.py (venv python)
Real processes and a real Terraform-free request path only (task creation);
it does not run Terraform, Ollama or AWS.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NPM = "npm.cmd" if sys.platform == "win32" else "npm"


def req(url, data=None, timeout=15):
    r = urllib.request.Request(
        url,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if data is None else "POST",
    )
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            return x.status, x.headers.get("content-type", ""), x.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read().decode()


def wait(url, tries=60):
    for _ in range(tries):
        try:
            if req(url)[0] == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(url)


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        raise SystemExit(1)


def main():
    procs = []
    try:
        procs.append(subprocess.Popen(
            [str(ROOT / ".venv/Scripts/python.exe"), "-m", "uvicorn", "engine.api:app",
             "--host", "127.0.0.1", "--port", "8000"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        wait("http://127.0.0.1:8000/api/health")
        procs.append(subprocess.Popen([NPM, "run", "dev"], cwd=ROOT / "web",
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        wait("http://127.0.0.1:5173/")
        for base in ["http://127.0.0.1:8000", "http://127.0.0.1:5173"]:
            s, _, b = req(base + "/api/health")
            check(f"{base}/api/health", s == 200 and json.loads(b)["cloud_apply"] is False)
            s, ct, b = req(base + "/api/nope")
            check(f"{base}/api/nope is JSON 404", s == 404 and "json" in ct and "<html" not in b.lower())
        check("/docs via Vite", req("http://127.0.0.1:5173/docs")[0] == 200)
        check("/openapi.json via Vite", req("http://127.0.0.1:5173/openapi.json")[0] == 200)
        s, _, b = req("http://127.0.0.1:5173/api/tasks", {"task": "Delete the production RDS database"})
        check("unsupported -> structured error via proxy",
              s == 400 and json.loads(b)["detail"]["error"] == "UNSUPPORTED_OPERATION")
        s, _, b = req("http://127.0.0.1:5173/api/tasks", {"task": "Increase memory for dev-api Lambda"})
        t = json.loads(b)
        check("supported task created via proxy", s == 200 and t["stage"] == "draft")
        print("Smoke test passed.")
    finally:
        for p in procs:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True) \
                if sys.platform == "win32" else p.terminate()


if __name__ == "__main__":
    main()
