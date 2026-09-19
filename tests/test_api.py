from fastapi.testclient import TestClient
from engine import api
from engine.pipeline import Pipeline


def test_contract_boundary_and_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    client = TestClient(api.app)
    t = client.post(
        "/api/tasks", json={"task": "Increase dev-api Lambda memory"}
    ).json()
    id = t["id"]
    assert client.post(f"/api/tasks/{id}/agent", json={}).status_code == 409
    assert (
        client.post(f"/api/tasks/{id}/confirm", json=t["contract"]).status_code == 200
    )
    assert (
        client.post(f"/api/tasks/{id}/confirm", json=t["contract"]).status_code == 409
    )
    assert client.post(f"/api/tasks/{id}/apply", json={}).status_code == 409
    assert [e["kind"] for e in client.get(f"/api/tasks/{id}/audit").json()] == [
        "draft",
        "human_confirmation",
    ]
    assert Pipeline(tmp_path).store.get(id)["contract"]["status"] == "confirmed"


def test_fuzzy_deny_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    client = TestClient(api.app)
    t = client.post("/api/tasks", json={"task": "Increase memory"}).json()
    c = t["contract"]
    c["denies"] = ["anything scary"]
    assert client.post(f"/api/tasks/{t['id']}/confirm", json=c).status_code == 409


def test_cross_origin_blocked():
    client = TestClient(api.app)
    assert (
        client.post(
            "/api/tasks",
            json={"task": "untrusted"},
            headers={"Origin": "https://example.com"},
        ).status_code
        == 403
    )


def test_api_is_independent_of_frontend_build(monkeypatch):
    # Phase 2: the API never serves the frontend; there is no static mount.
    from starlette.staticfiles import StaticFiles

    assert not any(
        isinstance(getattr(r, "app", None), StaticFiles) for r in api.app.routes
    )
    client = TestClient(api.app)
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["cloud_apply"] is False
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_unknown_routes_are_json_404_not_html():
    client = TestClient(api.app)
    for path in ["/api/nope", "/api/tasks/x/nope", "/", "/index.html"]:
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/json"), path
        assert "<html" not in r.text.lower()


def test_vite_origin_allowed_for_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    client = TestClient(api.app)
    r = client.post(
        "/api/tasks",
        json={"task": "Increase dev-api Lambda memory"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert r.status_code == 200


def test_openapi_lists_task_endpoints():
    schema = TestClient(api.app).get("/openapi.json").json()
    assert schema["info"]["title"] == "PlanReview"
    for path in ["/api/health", "/api/tasks", "/api/tasks/{id}/apply", "/api/tasks/{id}/audit"]:
        assert path in schema["paths"], path
