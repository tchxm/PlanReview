"""Bounded load test against a REAL uvicorn process (isolated data dir, fixed request budget).

Measures throughput and latency percentiles for authenticated reads and task creation under
concurrency, and (if psutil is installed) the server process RSS before and after.
Deliberately bounded: it is a regression tripwire, not a capacity claim.

  python tools/load_test.py            # ~15 s
"""

import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import auth  # noqa: E402

PORT = 8123
SECRET = "load-test-secret-" + "q" * 32
BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, token, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=None if body is None else json.dumps(body).encode(), headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    return code, (time.perf_counter() - t0) * 1000


def burst(label, n, workers, fn):
    lat, codes, lock = [], {}, threading.Lock()
    idx = iter(range(n))

    def work():
        for _ in idx:
            code, ms = fn()
            with lock:
                lat.append(ms)
                codes[code] = codes.get(code, 0) + 1

    t0 = time.perf_counter()
    ts = [threading.Thread(target=work) for _ in range(workers)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    wall = time.perf_counter() - t0
    lat.sort()
    p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))]
    print(f"{label:<28} n={n:<4} workers={workers:<3} {n / wall:7.1f} req/s  p50={p(.5):6.1f}ms p95={p(.95):6.1f}ms max={lat[-1]:6.1f}ms  codes={codes}")
    return codes


def rss(pid):
    try:
        import psutil

        return round(psutil.Process(pid).memory_info().rss / 1e6, 1)
    except Exception:
        return None


def main():
    data = tempfile.mkdtemp(prefix="pr-load-")
    env = dict(os.environ, PLANREVIEW_API_SECRET=SECRET, PLANREVIEW_DATA_DIR=data)
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "engine.api:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tok = auth.mint(SECRET.encode(), ["read", "write"], 600)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/api/health", timeout=1).read()
                break
            except Exception:
                time.sleep(0.5)
        print(f"platform={sys.platform} python={sys.version.split()[0]} rss_start_MB={rss(srv.pid)}")
        ok = True
        ok &= set(burst("health (public)", 400, 16, lambda: call("GET", "/api/health", tok))) == {200}
        ok &= set(burst("unauthenticated -> 401", 200, 8, lambda: call("GET", "/api/tasks", "bad.token"))) == {401}
        ok &= set(burst("create task (write)", 60, 8, lambda: call("POST", "/api/tasks", tok, {"task": "Increase memory for dev-api Lambda"}))) == {200}
        ok &= set(burst("list tasks (read)", 200, 16, lambda: call("GET", "/api/tasks", tok))) == {200}
        print(f"rss_end_MB={rss(srv.pid)}")
        print("LOAD TEST", "PASSED (no unexpected status codes)" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        srv.terminate()
        srv.wait(10)


if __name__ == "__main__":
    sys.exit(main())
