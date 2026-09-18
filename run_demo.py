"""Reproducible local replay. CLI explicitly records scripted demo confirmations."""

import argparse, json
from engine.pipeline import Pipeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scripted",
        action="store_true",
        help="Record automated DEMO confirmation/resolution; not human approval",
    )
    parser.add_argument(
        "--keep-deny",
        action="store_true",
        help="Leave the console on the three-verdict run",
    )
    args = parser.parse_args()
    p = Pipeline()
    t = p.create(
        "Increase memory for dev-api Lambda; send unanticipated networking changes to human review. Production and public access are forbidden."
    )
    id = t["id"]
    c = t["contract"]
    c["denies"] = ["production", "public_access"]
    c["max_changed_resources"] = 3
    print("DRAFT", json.dumps(c, indent=2))
    if (
        not args.scripted
        and input("Type CONFIRM to seal this demo scope: ") != "CONFIRM"
    ):
        return
    t = p.confirm(id, c)
    p.store.save(
        t,
        "demo_confirmation_source",
        {"source": "scripted demo" if args.scripted else "interactive CLI"},
    )
    print("CONFIRMED", id)
    p.agent(id)
    print("EDITED: offline fixture replay (not Strands)")
    p.plan(id)
    p.canonicalize(id)
    t = p.evaluate(id)
    for v in t["runs"][-1]["verdicts"]:
        print(v["verdict"], v["address"], v["reason"])
    t = p.apply(id)
    print("APPLY", t["runs"][-1]["apply_result"])
    if not args.keep_deny:
        if (
            not args.scripted
            and input(
                "Type RESOLVE to reject public access, re-plan, and approve the SG review: "
            )
            != "RESOLVE"
        ):
            return
        p.store.save(
            t,
            "remediation_requested",
            {
                "reject": "S3 public access",
                "source": "scripted demo" if args.scripted else "interactive CLI",
            },
        )
        p.agent(id, "review")
        p.plan(id)
        p.canonicalize(id)
        t = p.evaluate(id)
        reviews = {
            v["address"]: "approve"
            for v in t["runs"][-1]["verdicts"]
            if v["verdict"] == "REVIEW"
        }
        p.resolve(id, reviews)
        t = p.apply(id)
        for v in t["runs"][-1]["verdicts"]:
            print(v["verdict"], v["address"])
        print("APPLY", t["runs"][-1]["apply_result"])
        print(
            "AWS apply remains disabled. Successful real local apply proof: pytest tests/test_gate.py::test_real_local_apply"
        )
    print("AUDIT", len(p.store.audit(id)), "stored events; task", id)


if __name__ == "__main__":
    main()
