from pathlib import Path
import cedarpy
from engine.evaluator import POLICY, evaluate
from tests.test_engine import contract, changes


def test_policy_schema():
    schema = (Path(__file__).parents[1] / "schema/planreview.cedarschema").read_text()
    result = cedarpy.validate_policies(POLICY.read_text(), schema)
    assert not result.errors, result.errors


def test_determining_policies_distinguish_review():
    sg = next(c for c in changes("review") if c.resource_type == "aws_security_group")
    review = evaluate(contract(denies=("production", "public_access")), sg)
    deny = evaluate(contract(), sg)
    assert review.verdict == "REVIEW" and review.determining_policies == []
    assert deny.verdict == "DENY" and deny.determining_policies
