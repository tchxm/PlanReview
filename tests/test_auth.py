import time

import pytest
from fastapi.testclient import TestClient

from engine import api, auth
from engine.pipeline import Pipeline
from tests.conftest import SECRET, token

ENDPOINTS = [
    ("GET", "/api/tasks"),
    ("POST", "/api/tasks"),
    ("GET", "/api/tasks/x"),
    ("GET", "/api/tasks/x/intent"),
    ("POST", "/api/tasks/x/confirm"),
    ("POST", "/api/tasks/x/agent"),
    ("POST", "/api/tasks/x/plan"),
    ("POST", "/api/tasks/x/canonicalize"),
    ("POST", "/api/tasks/x/evaluate"),
    ("POST", "/api/tasks/x/resolve"),
    ("POST", "/api/tasks/x/apply"),
    ("GET", "/api/tasks/x/audit"),
    ("GET", "/api/tasks/x/evidence/1"),
    ("GET", "/api/auth/whoami"),
    ("POST", "/api/auth/revoke"),
]


def anon():
    return TestClient(api.app, headers={})


def send(client, method, path, headers=None):
    kw = {"headers": headers or {}}
    if method == "POST":
        kw["json"] = {}
    return client.request(method, path, **kw)


def code(r):
    return r.json()["detail"]["error"]


def test_health_is_public_and_leaks_nothing():
    r = anon().get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["auth"] == "required" and body["cloud_apply"] is False
    assert set(body) == {"status", "evaluator", "cloud_apply", "emulator_apply", "auth", "api_version"}
    assert body["emulator_apply"] is False


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_missing_credential_rejected_everywhere(method, path):
    r = send(anon(), method, path)
    assert r.status_code == 401 and code(r) == "AUTH_REQUIRED"
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_invalid_credential_rejected_everywhere(method, path):
    bad = token()[:-3] + "AAA"
    for header in ({"Authorization": "Bearer " + bad}, {"Authorization": "Bearer garbage"}, {"Authorization": "Basic abc"}):
        r = send(anon(), method, path, header)
        assert r.status_code == 401, (method, path, header)
        assert code(r) in ("AUTH_INVALID", "AUTH_REQUIRED")


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_expired_credential_rejected_everywhere(method, path):
    old = token(ttl=1, now=time.time() - 100)
    r = send(anon(), method, path, {"Authorization": "Bearer " + old})
    assert r.status_code == 401 and code(r) == "AUTH_EXPIRED"


def test_token_signed_with_another_secret_is_rejected():
    forged = auth.mint(b"a-different-secret-" + b"y" * 32, ["read", "write", "evidence"], 3600)
    r = send(anon(), "GET", "/api/tasks", {"Authorization": "Bearer " + forged})
    assert r.status_code == 401 and code(r) == "AUTH_INVALID"


def test_tampered_scope_or_expiry_invalidates_signature():
    t = token(["read"])
    _, sub, scope, exp, jti, sig = t.split(".")
    for forged in (f"v2.{sub}.read+write.{exp}.{jti}.{sig}", f"v2.{sub}.{scope}.{int(exp) + 99999}.{jti}.{sig}", f"v2.admin.{scope}.{exp}.{jti}.{sig}"):
        r = send(anon(), "POST", "/api/tasks", {"Authorization": "Bearer " + forged})
        assert r.status_code == 401 and code(r) == "AUTH_INVALID"


def test_read_scope_cannot_mutate_or_read_raw_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    read_only = {"Authorization": "Bearer " + token(["read"])}
    c = anon()
    assert c.get("/api/tasks", headers=read_only).status_code == 200
    r = c.post("/api/tasks", json={"task": "Increase dev-api Lambda memory"}, headers=read_only)
    assert r.status_code == 403 and code(r) == "AUTH_SCOPE"
    r = c.get("/api/tasks/x/evidence/1", headers=read_only)
    assert r.status_code == 403 and code(r) == "AUTH_SCOPE"


def test_write_scope_cannot_read_raw_evidence():
    r = anon().get("/api/tasks/x/evidence/1", headers={"Authorization": "Bearer " + token(["read", "write"])})
    assert r.status_code == 403 and code(r) == "AUTH_SCOPE"


def test_whoami_reports_scopes_and_expiry_only():
    r = anon().get("/api/auth/whoami", headers={"Authorization": "Bearer " + token(["read"], ttl=600)})
    assert r.status_code == 200
    assert r.json()["scopes"] == ["read"] and r.json()["expires_at"] > time.time()
    assert "token" not in r.text and "secret" not in r.text.lower()


def test_error_responses_never_echo_the_credential():
    t = token()
    r = anon().get("/api/tasks/nope", headers={"Authorization": "Bearer " + t[:-2] + "zz"})
    assert t[:-2] not in r.text
    r = anon().get("/api/tasks/nope", headers={"Authorization": "Bearer " + t})
    assert t not in r.text


def test_origin_protection_still_applies_with_a_valid_token():
    r = TestClient(api.app).post("/api/tasks", json={"task": "x"}, headers={"Origin": "http://evil.example", "Authorization": "Bearer " + token()})
    assert r.status_code == 403 and code(r) == "ORIGIN_BLOCKED"


def test_untrusted_host_still_rejected():
    r = TestClient(api.app, base_url="http://evil.example").get("/api/health")
    assert r.status_code == 400


def test_secret_and_mint_validation(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        auth.mint(SECRET, [], 60)
    with pytest.raises(ValueError):
        auth.mint(SECRET, ["admin"], 60)
    with pytest.raises(ValueError):
        auth.mint(SECRET, ["read"], 0)
    monkeypatch.setenv("PLANREVIEW_API_SECRET", "short")
    with pytest.raises(RuntimeError):
        auth.load_secret(tmp_path)


def test_generated_secret_file_is_created_once_and_not_in_repo(tmp_path, monkeypatch):
    monkeypatch.delenv("PLANREVIEW_API_SECRET")
    s1 = auth.load_secret(tmp_path)
    s2 = auth.load_secret(tmp_path)
    assert s1 == s2 and len(s1) >= 64
    assert (tmp_path / "api_secret").exists()
    # data/ is gitignored, so a generated secret can never be committed by accident
    assert "data/" in open(".gitignore").read()


def test_whoami_reports_identity():
    r = anon().get("/api/auth/whoami", headers={"Authorization": "Bearer " + auth.mint(SECRET, ["read"], 600, sub="alice@corp")})
    assert r.json()["sub"] == "alice@corp"


def test_mint_rejects_bad_subject():
    for bad in ("", "a.b", "x" * 65, "sp ace"):
        with pytest.raises(ValueError):
            auth.mint(SECRET, ["read"], 60, sub=bad)


def test_revoked_token_is_rejected_immediately_others_unaffected(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    t1 = auth.mint(SECRET, ["read"], 600, sub="alice")
    t2 = auth.mint(SECRET, ["read"], 600, sub="bob")
    h1, h2 = {"Authorization": "Bearer " + t1}, {"Authorization": "Bearer " + t2}
    c = anon()
    assert c.get("/api/tasks", headers=h1).status_code == 200
    assert c.post("/api/auth/revoke", headers=h1).json() == {"revoked": True}
    r = c.get("/api/tasks", headers=h1)
    assert r.status_code == 401 and code(r) == "AUTH_REVOKED"
    assert c.get("/api/tasks", headers=h2).status_code == 200


def test_revocation_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    t = auth.mint(SECRET, ["read"], 600)
    anon().post("/api/auth/revoke", headers={"Authorization": "Bearer " + t})
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    r = anon().get("/api/tasks", headers={"Authorization": "Bearer " + t})
    assert r.status_code == 401 and code(r) == "AUTH_REVOKED"
