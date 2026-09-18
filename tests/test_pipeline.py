import pytest
from engine.pipeline import Pipeline


def test_real_pipeline_and_resolution_binding(tmp_path):
    p = Pipeline(tmp_path)
    t = p.create("Demo scope")
    id = t["id"]
    c = t["contract"]
    c["denies"] = ["production", "public_access"]
    c["max_changed_resources"] = 3
    p.confirm(id, c)
    p.agent(id)
    p.plan(id)
    p.canonicalize(id)
    t = p.evaluate(id)
    assert {v["verdict"] for v in t["runs"][-1]["verdicts"]} == {
        "ALLOW",
        "REVIEW",
        "DENY",
    }
    with pytest.raises(ValueError, match="Only REVIEW"):
        p.resolve(id, {"aws_s3_bucket_public_access_block.assets": "approve"})
    p.resolve(id, {"aws_security_group.api": "approve"})
    t = p.apply(id)
    assert t["runs"][-1]["apply_result"]["spawned"] is False
    p.agent(id, "review")
    p.plan(id)
    p.canonicalize(id)
    t = p.evaluate(id)
    assert not t["runs"][-1]["resolutions"]
    assert (
        p.apply(id)["runs"][-1]["apply_result"]["reason"]
        == "1 unresolved or rejected REVIEW"
    )
    p.resolve(id, {"aws_security_group.api": "approve"})
    t = p.apply(id)
    assert "AWS apply disabled" in t["runs"][-1]["apply_result"]["reason"]
    # Stored audit remains usable without Terraform or the evaluator running.
    events = Pipeline(tmp_path).store.audit(id)
    assert any("raw_plan" in e["data"] for e in events if e["kind"] == "plan")
    assert any(e["kind"] == "human_resolution" for e in events)
    assert len(t["runs"]) == 2
