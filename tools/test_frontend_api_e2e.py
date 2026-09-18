"""Test the exact API endpoints called by the React frontend across all 5 screens."""

import json
from fastapi.testclient import TestClient
from engine.api import app, pipeline
from engine.pipeline import Pipeline, ROOT

def test_frontend_flow():
    client = TestClient(app)
    
    print("--- 1. Health Endpoint ---")
    r = client.get("/api/health")
    assert r.status_code == 200
    health = r.json()
    print("Health response:", health)
    assert health["status"] == "ok"
    assert health["evaluator"] == "cedar"
    assert health["cloud_apply"] is False
    
    print("\n--- 2. Screen 01: Create Task ---")
    task_desc = "Increase dev-api Lambda memory to 1024MB; send networking to review."
    r = client.post("/api/tasks", json={"task": task_desc, "mode": "replay"})
    assert r.status_code == 200
    task = r.json()
    task_id = task["id"]
    print(f"Created task {task_id}, stage: {task['stage']}, mode: {task['mode']}")
    assert task["stage"] == "draft"
    assert task["mode"] == "replay"
    
    print("\n--- 3. Screen 02: Confirm Contract ---")
    contract = task["contract"]
    contract["denies"] = ["production", "public_access"] # Demo 3-color scope
    contract["max_changed_resources"] = 3
    r = client.post(f"/api/tasks/{task_id}/confirm", json=contract)
    assert r.status_code == 200
    confirmed_task = r.json()
    print(f"Confirmed task, status: {confirmed_task['contract']['status']}, hash: {confirmed_task.get('confirmed_contract_hash')[:12]}...")
    assert confirmed_task["contract"]["status"] == "confirmed"
    assert confirmed_task["stage"] == "confirmed"
    
    # Verify contract immutability (cannot re-confirm)
    r_bad = client.post(f"/api/tasks/{task_id}/confirm", json=contract)
    assert r_bad.status_code == 409
    print("Contract re-confirmation safely rejected (HTTP 409)")
    
    print("\n--- 4. Screen 03: Plan Review (Agent -> Plan -> Canonicalize -> Evaluate) ---")
    # Step 4a: Agent edits
    r = client.post(f"/api/tasks/{task_id}/agent?variant=poisoned")
    assert r.status_code == 200
    print("Agent edits staged (poisoned fixture)")
    
    # Step 4b: Plan
    r = client.post(f"/api/tasks/{task_id}/plan")
    assert r.status_code == 200
    plan_data = r.json()
    run = plan_data["runs"][-1]
    print(f"Terraform plan generated, run id: {run['id'][:8]}, plan hash: {run['plan_hash'][:12]}...")
    
    # Step 4c: Canonicalize
    r = client.post(f"/api/tasks/{task_id}/canonicalize")
    assert r.status_code == 200
    canon_data = r.json()
    canon_changes = canon_data["runs"][-1]["canonical"]
    print(f"Canonicalized {len(canon_changes)} resource changes")
    
    # Step 4d: Evaluate with Cedar
    r = client.post(f"/api/tasks/{task_id}/evaluate")
    assert r.status_code == 200
    eval_data = r.json()
    verdicts = eval_data["runs"][-1]["verdicts"]
    print("Cedar verdicts:")
    for v in verdicts:
        print(f"  [{v['verdict']}] {v['address']} -> {v['reason']}")
        
    verdict_types = {v["verdict"] for v in verdicts}
    assert "ALLOW" in verdict_types
    assert "REVIEW" in verdict_types
    assert "DENY" in verdict_types
    
    # Step 4e: Verify Apply Gate Blocks via API
    r = client.post(f"/api/tasks/{task_id}/apply")
    assert r.status_code == 200
    apply_res = r.json()["runs"][-1]["apply_result"]
    print("Apply Gate response:", apply_res)
    assert apply_res["status"] == "BLOCKED"
    assert apply_res["spawned"] is False
    assert "DENY" in apply_res["reason"]
    
    print("\n--- 5. Screen 04: Resolution ---")
    # Try resolving a DENY (should fail)
    r_bad_res = client.post(f"/api/tasks/{task_id}/resolve", json={"aws_s3_bucket_public_access_block.assets": "approve"})
    assert r_bad_res.status_code == 409
    print("Resolving DENY safely rejected (HTTP 409)")
    
    # Resolve the REVIEW
    r_res = client.post(f"/api/tasks/{task_id}/resolve", json={"aws_security_group.api": "approve"})
    assert r_res.status_code == 200
    print("Recorded resolution: aws_security_group.api = approve")
    
    # Re-plan Lambda only (intended variant) to clear the DENY
    client.post(f"/api/tasks/{task_id}/agent?variant=intended")
    client.post(f"/api/tasks/{task_id}/plan")
    client.post(f"/api/tasks/{task_id}/canonicalize")
    r_eval2 = client.post(f"/api/tasks/{task_id}/evaluate")
    assert r_eval2.status_code == 200
    verdicts2 = r_eval2.json()["runs"][-1]["verdicts"]
    print(f"Fresh plan evaluated with {len(verdicts2)} changes: {[v['verdict'] for v in verdicts2]}")
    assert all(v["verdict"] == "ALLOW" for v in verdicts2)
    
    print("\n--- 6. Screen 05: Audit Trail ---")
    r = client.get(f"/api/tasks/{task_id}/audit")
    assert r.status_code == 200
    events = r.json()
    print(f"Persisted audit events count: {len(events)}")
    kinds = [e["kind"] for e in events]
    print("Event sequence:", kinds)
    assert "draft" in kinds
    assert "human_confirmation" in kinds
    assert "agent_edits" in kinds
    assert "plan" in kinds
    assert "canonical" in kinds
    assert "verdicts" in kinds
    assert "apply_result" in kinds
    
    # Verify raw_plan is retained in plan audit event
    plan_event = next(e for e in events if e["kind"] == "plan")
    assert "raw_plan" in plan_event["data"]
    
    print("\n--- 7. Live vs Replay Mode Labeling Check ---")
    # Live mode task
    r_live = client.post("/api/tasks", json={"task": "live task test", "mode": "ollama"})
    assert r_live.json()["mode"] == "ollama"
    print("Replay mode correctly identifies 'replay'; Ollama mode correctly identifies 'ollama'.")
    
    print("\nALL FRONTEND API FLOWS FULLY VERIFIED PASS!")

if __name__ == "__main__":
    test_frontend_flow()

