"""Ollama failure modes against REAL sockets (a closed port and a local fake HTTP server),
not mocks: unavailable, missing model, malformed responses, timeout and recovery.
None of these may ever create a task or fall back to replay."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from engine import api
from engine.intent import canonical_address
from engine.pipeline import Pipeline


class Fake:
    def __init__(self, models=("llama3.2:3b",), tags_body=None, chat="ok", chat_content=None, delay=0.0):
        self.models, self.tags_body, self.chat, self.chat_content, self.delay = models, tags_body, chat, chat_content, delay
        self.server = None

    def handler(fake):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/api/tags":
                    if fake.tags_body is not None:
                        return self._send(200, fake.tags_body, "text/plain")
                    return self._send(200, {"models": [{"model": m, "name": m} for m in fake.models]})
                self._send(404, {"error": "nope"})

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path != "/api/chat":
                    return self._send(404, {"error": "nope"})
                time.sleep(fake.delay)
                if fake.chat == "http500":
                    return self._send(500, {"error": "boom"})
                content = fake.chat_content if fake.chat_content is not None else json.dumps(
                    {"operation": "update_memory", "resource_address": "dev-api-Lambda", "resource_type": "aws_lambda_function", "attribute": "memory_size", "requested_value": 512}
                )
                if fake.chat == "envelope_garbage":
                    return self._send(200, b"<html>not json</html>", "text/html")
                self._send(200, {"model": "llama3.2:3b", "created_at": "2026-01-01T00:00:00Z", "message": {"role": "assistant", "content": content}, "done": True})

        return H

    def start(self, port=0):
        self.server = ThreadingHTTPServer(("127.0.0.1", port), self.handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.server.server_address[1]

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    monkeypatch.setenv("PLANREVIEW_OLLAMA_TIMEOUT", "2")
    monkeypatch.setenv("PLANREVIEW_OLLAMA_CHAT_TIMEOUT", "2")
    return TestClient(api.app, raise_server_exceptions=False)


def host(monkeypatch, port):
    monkeypatch.setenv("PLANREVIEW_OLLAMA_HOST", f"http://127.0.0.1:{port}")


def create(client, text="Increase dev-api Lambda memory to 512 MB"):
    return client.post("/api/tasks", json={"task": text, "mode": "ollama"})


def code(r):
    return r.json()["detail"]["error"]


def assert_no_task_no_replay(client):
    assert client.get("/api/tasks").json() == []


def test_server_down_real_closed_port_is_503_and_never_replay(client, monkeypatch):
    host(monkeypatch, free_port())
    r = create(client)
    assert r.status_code == 503 and code(r) == "MODEL_UNAVAILABLE"
    assert_no_task_no_replay(client)


def test_missing_model_is_503(client, monkeypatch):
    fake = Fake(models=("some-other-model:1b",))
    host(monkeypatch, fake.start())
    try:
        r = create(client)
        assert r.status_code == 503 and code(r) == "MODEL_UNAVAILABLE"
        assert r.json()["detail"]["details"]["model_installed"] is False
        assert_no_task_no_replay(client)
    finally:
        fake.stop()


def test_configurable_model_name_is_honoured(client, monkeypatch):
    fake = Fake(models=("qwen2.5:7b",))
    host(monkeypatch, fake.start())
    monkeypatch.setenv("PLANREVIEW_OLLAMA_MODEL", "qwen2.5:7b")
    try:
        assert create(client).status_code == 200
    finally:
        fake.stop()


def test_malformed_model_list_is_503(client, monkeypatch):
    fake = Fake(tags_body=b"this is not json")
    host(monkeypatch, fake.start())
    try:
        r = create(client)
        assert r.status_code == 503 and code(r) == "MODEL_UNAVAILABLE"
        assert_no_task_no_replay(client)
    finally:
        fake.stop()


@pytest.mark.parametrize("content", ["definitely not json", "[1, 2, 3]", "```json\n{broken\n```"])
def test_malformed_model_answer_is_502_and_creates_nothing(client, monkeypatch, content):
    fake = Fake(chat_content=content)
    host(monkeypatch, fake.start())
    try:
        r = create(client)
        assert r.status_code == 502 and code(r) == "MODEL_RESPONSE_INVALID"
        assert_no_task_no_replay(client)
    finally:
        fake.stop()


def test_http_error_from_the_model_server_is_not_a_success(client, monkeypatch):
    fake = Fake(chat="http500")
    host(monkeypatch, fake.start())
    try:
        r = create(client)
        assert r.status_code in (502, 503) and code(r) in {"MODEL_UNAVAILABLE", "MODEL_RESPONSE_INVALID"}
        assert_no_task_no_replay(client)
    finally:
        fake.stop()


def test_slow_model_times_out_as_unavailable(client, monkeypatch):
    fake = Fake(delay=4)
    host(monkeypatch, fake.start())
    monkeypatch.setenv("PLANREVIEW_OLLAMA_CHAT_TIMEOUT", "1")
    try:
        t0 = time.time()
        r = create(client)
        assert r.status_code == 503 and code(r) == "MODEL_UNAVAILABLE"
        assert time.time() - t0 < 3.5
        assert_no_task_no_replay(client)
    finally:
        fake.stop()


def test_recovery_after_the_server_comes_back(client, monkeypatch):
    port = free_port()
    host(monkeypatch, port)
    assert create(client).status_code == 503
    assert_no_task_no_replay(client)
    fake = Fake()
    fake.start(port)
    try:
        r = create(client)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "ollama" and body["intent"]["status"] == "VALIDATED"
        assert body["intent"]["resource_address"] == "aws_lambda_function.dev_api"
        assert body["intent"]["mapped_from"] == "dev-api-Lambda"
        assert "allowlist" in body["intent"]["reason"]
    finally:
        fake.stop()


def test_remote_host_is_refused_without_contacting_it(client, monkeypatch):
    monkeypatch.setenv("PLANREVIEW_OLLAMA_HOST", "http://203.0.113.9:11434")
    r = create(client)
    assert r.status_code == 503 and code(r) == "MODEL_UNAVAILABLE"
    assert_no_task_no_replay(client)


# ---- deterministic allowlist ---------------------------------------------------
@pytest.mark.parametrize("name", ["dev-api-Lambda", "Dev API Lambda", "dev_api", "aws_lambda_function.dev_api", "DEV-API"])
def test_known_lambda_names_map_to_the_canonical_address(name):
    assert canonical_address(name, "update_memory") == "aws_lambda_function.dev_api"


@pytest.mark.parametrize("name", ["assets bucket", "assets", "aws_s3_bucket.assets", "Dev Assets Bucket"])
def test_known_bucket_names_map_to_the_canonical_address(name):
    assert canonical_address(name, "update_tags") == "aws_s3_bucket.assets"


@pytest.mark.parametrize(
    "name,op",
    [("prod-db", "update_memory"), ("assets", "update_memory"), ("dev-api", "update_tags"), ("lambda", "update_memory"), ("", "update_memory"), ("aws_lambda_function.other", "update_memory"), ("*", "update_tags")],
)
def test_unknown_or_cross_operation_names_are_never_guessed(name, op):
    assert canonical_address(name, op) is None


def test_allowlist_does_not_bypass_capability_validation(client, monkeypatch):
    """A model that names an unsupported thing is still rejected by the validator."""
    bad = json.dumps({"operation": "update_memory", "resource_address": "prod-db", "resource_type": "aws_db_instance", "attribute": "memory_size", "requested_value": 512})
    fake = Fake(chat_content=bad)
    host(monkeypatch, fake.start())
    try:
        r = create(client, "Increase prod-db memory")
        assert r.status_code == 400 and code(r) == "UNSUPPORTED_OPERATION"
        assert_no_task_no_replay(client)
    finally:
        fake.stop()
