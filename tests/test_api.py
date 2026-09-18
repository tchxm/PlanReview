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
