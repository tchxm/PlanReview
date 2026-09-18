import json, shutil, subprocess, uuid, threading, re, hashlib
from pathlib import Path
from datetime import datetime, timezone
from engine.storage import Store
from engine.contract import draft, confirm
from engine.types import Contract
from engine.canonicalizer import canonicalize
from engine.evaluator import evaluate_all
from engine.gate import apply_saved, digest

ROOT = Path(__file__).resolve().parents[1]
LOCK = threading.RLock()


def contract_digest(contract):
    """Stable integrity binding for a confirmed contract stored in local SQLite."""
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def assert_contract_integrity(task):
    """Reject direct persistence tampering before any pipeline stage uses a contract."""
    if task.get("contract", {}).get("status") == "confirmed":
        expected = task.get("confirmed_contract_hash")
        actual = contract_digest(task["contract"])
        if not expected or expected != actual:
            raise ValueError("Confirmed contract integrity hash mismatch")


class Pipeline:
    def __init__(self, data=None):
        self.data = Path(data or ROOT / "data").resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data / "planreview.sqlite")

    def create(self, task, mode="replay"):
        if mode not in ["replay", "ollama"]:
            raise ValueError("Unknown mode")
        # The deterministic extractor remains the contract authority: repeated
        # constrained local-model outputs were schema-valid but lost scope text.
        c = draft(task)
        c = Contract.model_validate(
            {**c.model_dump(), "contract_id": str(uuid.uuid4())}
        )
        t = dict(
            id=c.contract_id,
            contract=c.model_dump(mode="json"),
            mode=mode,
            stage="draft",
            runs=[],
            resolutions={},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.store.save(t, "draft")
        return t

    def confirm(self, id, body=None):
        t = self.store.get(id)
        if t["contract"]["status"] != "draft":
            raise ValueError("Contract is immutable after confirmation")
        c = Contract.model_validate(body or t["contract"])
        if c.contract_id != id:
            raise ValueError("Contract ID cannot change")
        t["contract"] = confirm(c).model_dump(mode="json")
        t["confirmed_contract_hash"] = contract_digest(t["contract"])
        t["stage"] = "confirmed"
        self.store.save(t, "human_confirmation")
        return t

    def agent(self, id, variant="poisoned"):
        t = self.store.get(id)
        assert_contract_integrity(t)
        if not Contract.model_validate(t["contract"]).active():
            raise ValueError("Active confirmed contract required")
        if variant not in ["baseline", "intended", "review", "poisoned"]:
            raise ValueError("Unknown fixture")
        workspace = self.data / "workspaces" / id
        if t.get("prepared"):
            raise ValueError("Plan the prepared edit before editing again")
        if not workspace.exists():
            source = ROOT / "terraform/fixtures/baseline"
            if not (source / "terraform.tfstate").exists():
                raise ValueError("Pipeline incomplete: run fixture generator first")
            workspace.mkdir(parents=True)
            for name in ["terraform.tfstate", "lambda.zip", ".terraform.lock.hcl"]:
                shutil.copy2(source / name, workspace / name)
        source = (
            ROOT
            / "terraform/fixtures"
            / ("baseline" if t["mode"] == "ollama" else variant)
            / "main.tf"
        )
        shutil.copy2(source, workspace / "main.tf")
        log = "Offline fixture replay; no LLM was invoked"
        if t["mode"] == "ollama":
            from engine.agent import live_edit

            log = live_edit(t["contract"]["task"], workspace)
        t["workspace"] = str(workspace)
        t["prepared"] = True
        t["stage"] = "edited"
        self.store.save(
            t,
            "agent_edits",
            {
                "mode": t["mode"],
                "variant": variant,
                "log": log,
                "terraform": (workspace / "main.tf").read_text(),
            },
        )
        return t

    def command(self, args, path):
        import os

        env = os.environ.copy()
        env["TF_PLUGIN_CACHE_DIR"] = str(ROOT / ".provider-cache")
        p = subprocess.run(
            ["terraform", *args],
            cwd=path,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if p.returncode:
            raise ValueError(p.stdout + p.stderr)
        return p.stdout

    def plan(self, id):
        t = self.store.get(id)
        assert_contract_integrity(t)
        if not t.get("prepared"):
            raise ValueError("Pipeline incomplete: run edits first")
        if not Contract.model_validate(t["contract"]).active():
            raise ValueError("Contract expired")
        path = Path(t["workspace"])
        config = (path / "main.tf").read_text()
        baseline = (ROOT / "terraform/fixtures/baseline/main.tf").read_text()
        if config.split("resource ", 1)[0] != baseline.split("resource ", 1)[
            0
        ] or re.search(r'\b(provisioner|data|module|backend)\s+"', config):
            raise ValueError(
                "Unsupported executable Terraform configuration; planning blocked"
            )
        if not (path / ".terraform").exists():
            self.command(["init", "-input=false", "-no-color"], path)
        rid = str(uuid.uuid4())
        plan_path = path / f"{rid}.tfplan"
        log = self.command(
            [
                "plan",
                "-refresh=false",
                "-input=false",
                "-no-color",
                f"-out={plan_path}",
            ],
            path,
        )
        raw = self.command(["show", "-json", str(plan_path)], path)
        raw_path = path / f"{rid}.json"
        raw_path.write_text(raw)
        run = dict(
            id=rid,
            created_at=datetime.now(timezone.utc).isoformat(),
            workspace=str(path),
            plan_path=str(plan_path),
            plan_hash=digest(plan_path),
            raw_path=str(raw_path),
            raw_hash=digest(raw_path),
            plan_stdout=log,
            canonical=None,
            verdicts=None,
            resolutions={},
            apply_result=None,
        )
        t["runs"].append(run)
        t["prepared"] = False
        t["stage"] = "planned"
        self.store.save(t, "plan", {**run, "raw_plan": json.loads(raw)})
        return t

    def canonicalize(self, id):
        t = self.store.get(id)
        assert_contract_integrity(t)
        run = self.latest(t)
        if digest(run["raw_path"]) != run["raw_hash"]:
            raise ValueError("Raw plan hash mismatch")
        run["canonical"] = [
            c.model_dump()
            for c in canonicalize(json.loads(Path(run["raw_path"]).read_text()))
        ]
        t["stage"] = "canonicalized"
        self.store.save(t, "canonical", run)
        return t

    def evaluate(self, id):
        from engine.types import CanonicalChange
        from engine.evaluator import POLICY

        t = self.store.get(id)
        assert_contract_integrity(t)
        run = self.latest(t)
        if run["canonical"] is None:
            raise ValueError("Pipeline incomplete: canonicalize first")
        run["verdicts"] = [
            v.model_dump()
            for v in evaluate_all(
                Contract.model_validate(t["contract"]),
                [CanonicalChange.model_validate(c) for c in run["canonical"]],
            )
        ]
        run["policy_hash"] = digest(POLICY)
        run["resolutions"] = {}
        t["stage"] = "evaluated"
        self.store.save(t, "verdicts", run)
        return t

    def resolve(self, id, resolutions):
        t = self.store.get(id)
        assert_contract_integrity(t)
        run = self.latest(t)
        if run["verdicts"] is None:
            raise ValueError("Pipeline incomplete: evaluate first")
        reviews = {v["address"] for v in run["verdicts"] if v["verdict"] == "REVIEW"}
        for address, decision in resolutions.items():
            if address not in reviews or decision not in ["approve", "reject"]:
                raise ValueError(
                    "Only REVIEW items accept approve/reject resolutions; DENY requires a new plan"
                )
        run["resolutions"].update(resolutions)
        t["stage"] = "resolved"
        self.store.save(
            t, "human_resolution", {"run_id": run["id"], "resolutions": resolutions}
        )
        return t

    def apply(self, id):
        from engine.evaluator import POLICY

        t = self.store.get(id)
        assert_contract_integrity(t)
        run = self.latest(t)
        if run["verdicts"] is None:
            raise ValueError("Pipeline incomplete: evaluate first")
        if (
            run.get("apply_result", {})
            and run["apply_result"].get("status") == "APPLIED"
        ):
            raise ValueError("Run already applied")
        if t.get("prepared"):
            raise ValueError("Unplanned edits exist; create and evaluate a new plan")
        if run.get("policy_hash") != digest(POLICY):
            raise ValueError(
                "Policies changed; evaluate again and resolve the new verdicts"
            )
        run["apply_result"] = apply_saved(
            Contract.model_validate(t["contract"]), run, run["resolutions"]
        )
        t["stage"] = run["apply_result"]["status"].lower()
        self.store.save(t, "apply_result", run["apply_result"])
        return t

    @staticmethod
    def latest(t):
        if not t["runs"]:
            raise ValueError("Pipeline incomplete: no saved plan")
        return t["runs"][-1]
