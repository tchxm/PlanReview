import contextlib, os, json, shutil, subprocess, uuid, threading, re, hashlib
from pathlib import Path
from datetime import datetime, timezone
from engine.storage import Store
from engine import capabilities
from engine.contract import draft, confirm
from engine.types import Contract
from engine.canonicalizer import canonicalize
from engine.evaluator import evaluate_all
from engine.gate import apply_saved, digest
from engine.intent import interpret
from engine.guard import verify_workspace_configuration
from engine.proc import report, run_tree
from engine.exceptions import (
    DependencyError, IntegrityError, InvalidRequestError, StateConflictError, TerraformError,
)
import logging

log = logging.getLogger("planreview")

ROOT = Path(__file__).resolve().parents[1]
LOCK = threading.RLock()  # legacy name, no longer used by the API


class TaskLocks:
    """Per-task mutation locks. Mutations of ONE task are serialized (so a plan, an edit
    or a resolution can never interleave on the same task or saved plan); different
    tasks proceed in parallel. In-process only: run a single Uvicorn worker (see docs)."""

    MAX = 5000

    def __init__(self):
        self._guard = threading.Lock()
        self._locks = {}

    def get(self, task_id):
        with self._guard:
            if len(self._locks) > self.MAX:  # drop idle entries created by unknown ids
                for k, lk in list(self._locks.items()):
                    if lk.acquire(blocking=False):
                        try:
                            del self._locks[k]
                        finally:
                            lk.release()
            return self._locks.setdefault(task_id, threading.RLock())


LOCKS = TaskLocks()


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
            raise IntegrityError("Confirmed contract integrity hash mismatch", code="CONTRACT_INTEGRITY_FAILED")


class Pipeline:
    def __init__(self, data=None):
        self.data = Path(data or os.environ.get("PLANREVIEW_DATA_DIR") or ROOT / "data").resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        from engine import auth as _auth
        from engine.storage import derive_audit_key

        from engine.vault import Vault

        secret = _auth.load_secret(self.data)
        self.vault = Vault(secret)
        self.store = Store(self.data / "planreview.sqlite", key=derive_audit_key(secret), vault=self.vault)

    def create(self, task, mode="replay"):
        if mode not in ["replay", "adversarial", "ollama", "live"]:
            raise InvalidRequestError("Unknown mode", code="UNKNOWN_MODE")

        # Extract structured intent and validate against capability registry
        intent_proposal = interpret(task, mode=mode)
        c = draft(task, mode=mode, intent=intent_proposal)
        c = Contract.model_validate(
            {**c.model_dump(), "contract_id": str(uuid.uuid4())}
        )
        t = dict(
            id=c.contract_id,
            contract=c.model_dump(mode="json"),
            mode=mode,
            intent=intent_proposal.model_dump() if intent_proposal else None,
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
            raise StateConflictError("Contract is immutable after confirmation", code="CONTRACT_IMMUTABLE")
        c = Contract.model_validate(body or t["contract"])
        if c.contract_id != id:
            raise InvalidRequestError("Contract ID cannot change", code="CONTRACT_ID_MISMATCH")
        t["contract"] = confirm(c).model_dump(mode="json")
        t["confirmed_contract_hash"] = contract_digest(t["contract"])
        t["stage"] = "confirmed"
        self.store.save(t, "human_confirmation")
        return t

    @staticmethod
    def _reuse_initialized_providers(workspace):
        """Hosted builds keep an initialized template (tools/install_terraform.py). Linking its providers and using
        its platform-correct lock file makes `terraform init` instant instead of re-downloading the AWS provider
        per task. Any problem (no template, no symlink permission) falls back to a normal init."""
        import os

        template = ROOT / ".tf-template"
        try:
            if (template / ".terraform" / "providers").is_dir() and (template / ".terraform.lock.hcl").exists():
                shutil.copy2(template / ".terraform.lock.hcl", workspace / ".terraform.lock.hcl")
                (workspace / ".terraform").mkdir(exist_ok=True)
                os.symlink(template / ".terraform" / "providers", workspace / ".terraform" / "providers", target_is_directory=True)
        except (OSError, NotImplementedError):
            shutil.rmtree(workspace / ".terraform", ignore_errors=True)

    def agent(self, id, variant="poisoned"):
        t = self.store.get(id)
        assert_contract_integrity(t)
        if not Contract.model_validate(t["contract"]).active():
            raise StateConflictError("Active confirmed contract required", code="CONTRACT_NOT_ACTIVE")
        if variant not in ["baseline", "intended", "review", "poisoned", "adversarial"]:
            raise InvalidRequestError("Unknown fixture", code="UNKNOWN_FIXTURE")
        workspace = self.data / "workspaces" / id
        if t.get("prepared"):
            raise StateConflictError("Plan the prepared edit before editing again", code="EDIT_ALREADY_PREPARED")
        if not workspace.exists():
            source = ROOT / "terraform/fixtures/baseline"
            if not (source / "terraform.tfstate").exists():
                raise DependencyError("Terraform fixtures are missing; run the fixture generator", code="FIXTURES_UNAVAILABLE")
            workspace.mkdir(parents=True)
            for name in ["terraform.tfstate", "lambda.zip", ".terraform.lock.hcl"]:
                shutil.copy2(source / name, workspace / name)
            self._reuse_initialized_providers(workspace)

        log = "Offline fixture replay; no LLM was invoked"
        t["agent_variant"] = variant

        if t["mode"] in ["ollama", "live"]:
            # Live AI agent mode: uses baseline main.tf and calls intent-gated live_edit
            shutil.copy2(ROOT / "terraform/fixtures/baseline/main.tf", workspace / "main.tf")
            from engine.agent import live_edit
            try:
                log = live_edit(t["contract"]["task"], workspace, intent=t.get("intent"), adversarial=False)
            except TypeError:
                log = live_edit(t["contract"]["task"], workspace)
        elif t["mode"] == "adversarial" or variant in ["poisoned", "adversarial"]:
            # Explicit adversarial demonstration
            source = ROOT / "terraform/fixtures/poisoned/main.tf"
            shutil.copy2(source, workspace / "main.tf")
            log = "Explicit adversarial demonstration replay; ALLOW/REVIEW/DENY verdicts generated"
        elif variant == "intended":
            # Normal replay: apply parameter-driven intended change
            shutil.copy2(ROOT / "terraform/fixtures/baseline/main.tf", workspace / "main.tf")
            intent = t.get("intent")
            if intent and intent.get("operation") == "update_memory":
                mem = intent.get("requested_value", 1024)
                w_main = (workspace / "main.tf").read_text(encoding="utf-8")
                (workspace / "main.tf").write_text(w_main.replace("memory_size = 512", f"memory_size = {mem}"), encoding="utf-8")
                log = f"Replay applied validated memory_size={mem} to dev_api Lambda"
            elif intent and intent.get("operation") == "update_tags":
                team = intent.get("requested_value", "core")
                w_main = (workspace / "main.tf").read_text(encoding="utf-8")
                rep = f'resource "aws_s3_bucket" "assets" {{\n  bucket = "planreview-demo-assets"\n  tags = {{ Environment = "dev", Team = "{team}" }}\n}}'
                (workspace / "main.tf").write_text(w_main.replace('resource "aws_s3_bucket" "assets" {\n  bucket = "planreview-demo-assets"\n  tags = { Environment = "dev" }\n}', rep), encoding="utf-8")
                log = f"Replay applied validated Team={team} tag to assets S3 bucket"
            elif intent and intent.get("operation") in capabilities.EDITS:
                base = (ROOT / "terraform/fixtures/baseline/main.tf").read_text(encoding="utf-8")
                (workspace / "main.tf").write_text(
                    capabilities.expected_config(base, intent["operation"], intent["attribute"], intent["requested_value"]), encoding="utf-8"
                )
                log = f"Replay applied validated {intent['operation']} ({intent['attribute']} = {intent['requested_value']!r})"
            else:
                shutil.copy2(ROOT / "terraform/fixtures/intended/main.tf", workspace / "main.tf")
        else:
            source = ROOT / "terraform/fixtures" / variant / "main.tf"
            shutil.copy2(source, workspace / "main.tf")

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
        env["TF_PLUGIN_CACHE_DIR"] = os.environ.get("PLANREVIEW_PLUGIN_CACHE") or str(ROOT / ".provider-cache")
        if os.environ.get("RENDER"):  # 512MB instance: keep the Go runtime (AWS provider) inside it
            env.setdefault("GOMEMLIMIT", "300MiB")
            env.setdefault("GOGC", "50")
        report(f"terraform {args[0]}")
        try:
            p = run_tree(
                ["terraform", *args],
                cwd=path,
                env=env,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("PLANREVIEW_TF_TIMEOUT", "180")),
            )
        except FileNotFoundError:
            raise DependencyError("The terraform binary was not found on PATH", code="TERRAFORM_UNAVAILABLE")
        except subprocess.TimeoutExpired:
            log.error("terraform %s timed out", args[0])
            raise TerraformError("Terraform timed out; inspect the workspace before retrying", code="TERRAFORM_TIMEOUT", status_code=504)
        if p.returncode:
            # Raw output can contain paths and values: keep it in the server log only.
            log.error("terraform %s failed (exit %s): %s", args[0], p.returncode, (p.stdout + p.stderr)[-4000:])
            raise TerraformError(
                f"terraform {args[0]} failed (exit {p.returncode}); details are in the server log",
                details={"command": args[0], "exit_code": p.returncode},
            )
        return p.stdout

    def plan(self, id):
        t = self.store.get(id)
        assert_contract_integrity(t)
        if not t.get("prepared"):
            raise StateConflictError("Pipeline incomplete: run edits first", code="STAGE_OUT_OF_ORDER")
        if not Contract.model_validate(t["contract"]).active():
            raise StateConflictError("Contract expired", code="CONTRACT_EXPIRED")
        path = Path(t["workspace"])

        # Pre-plan configuration and workspace integrity guard
        verify_workspace_configuration(
            workspace_path=path,
            contract=Contract.model_validate(t["contract"]),
            intent=t.get("intent"),
            mode=t["mode"],
            variant=t.get("agent_variant", "intended"),
            root_path=ROOT,
        )

        if not (path / ".terraform").exists():
            self.command(["init", "-input=false", "-no-color"], path)
        rid = str(uuid.uuid4())
        plan_path = path / f"{rid}.tfplan"
        raw_path = path / f"{rid}.json"
        # A plan is a pure function of (config, seed state). Hosted builds pre-compute it once with the real
        # Terraform (tools/warm_plans.py) because loading the AWS provider does not fit a small instance.
        key = hashlib.sha256(b"|".join((path / n).read_bytes() for n in ("main.tf", "terraform.tfstate", "lambda.zip"))).hexdigest()
        cached = ROOT / ".plan-cache" / key
        if (cached / "plan.tfplan").exists() and (cached / "plan.json").exists():
            shutil.copy2(cached / "plan.tfplan", plan_path)
            raw = (cached / "plan.json").read_text(encoding="utf-8")
            raw_path.write_text(raw)
            log = "Plan produced by a real `terraform plan` run at build time for this exact configuration and state. " + (
                (cached / "plan.log").read_text(encoding="utf-8") if (cached / "plan.log").exists() else ""
            )
        else:
            log = self.command(
                [
                    "plan",
                    "-refresh=false",
                    "-input=false",
                    "-no-color",
                    "-parallelism=1",
                    f"-out={plan_path}",
                ],
                path,
            )
            raw = self.command(["show", "-json", str(plan_path)], path)
            raw_path.write_text(raw)
            try:
                cached.mkdir(parents=True, exist_ok=True)
                shutil.copy2(plan_path, cached / "plan.tfplan")
                (cached / "plan.json").write_text(raw, encoding="utf-8")
                (cached / "plan.log").write_text(log, encoding="utf-8")
            except OSError:
                pass
        plan_hash, raw_hash = digest(plan_path), digest(raw_path)
        self.vault.seal(plan_path)  # plaintext plan artifacts never rest on disk (see engine/vault.py)
        self.vault.seal(raw_path)
        run = dict(
            id=rid,
            created_at=datetime.now(timezone.utc).isoformat(),
            workspace=str(path),
            plan_path=str(plan_path),
            plan_hash=plan_hash,
            raw_path=str(raw_path),
            raw_hash=raw_hash,
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
        try:
            raw_ok = self.vault.digest(run["raw_path"]) == run["raw_hash"]
        except (OSError, ValueError):
            raw_ok = False
        if not raw_ok:
            raise IntegrityError("Raw plan hash mismatch", code="PLAN_INTEGRITY_FAILED")
        run["canonical"] = [
            c.model_dump()
            for c in canonicalize(json.loads(self.vault.read_text(run["raw_path"])))
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
            raise StateConflictError("Pipeline incomplete: canonicalize first", code="STAGE_OUT_OF_ORDER")
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

    def resolve(self, id, resolutions, actor=None):
        t = self.store.get(id)
        assert_contract_integrity(t)
        run = self.latest(t)
        if run["verdicts"] is None:
            raise StateConflictError("Pipeline incomplete: evaluate first", code="STAGE_OUT_OF_ORDER")
        from engine.evaluator import POLICY as _POLICY

        if run.get("policy_hash") != digest(_POLICY):
            # Fail closed: never record an approval against verdicts made under a different policy.
            raise StateConflictError("Policies changed; evaluate again and resolve the new verdicts", code="POLICY_CHANGED")
        reviews = {v["address"] for v in run["verdicts"] if v["verdict"] == "REVIEW"}
        eval_errors = {
            v["address"]
            for v in run["verdicts"]
            if "Cedar evaluation unavailable" in v.get("reason", "")
            or "evaluation error" in v.get("reason", "").lower()
            or v.get("verdict") == "EVALUATION_ERROR"
        }
        for address, decision in resolutions.items():
            if address in eval_errors:
                raise StateConflictError(
                    f"Address {address} experienced an evaluation error and cannot be approved. Repair evaluation and re-run.",
                    code="EVALUATION_ERROR_NOT_APPROVABLE",
                )
            if address not in reviews or decision not in ["approve", "reject"]:
                raise StateConflictError(
                    "Only REVIEW items accept approve/reject resolutions; DENY requires a new plan",
                    code="RESOLUTION_NOT_ALLOWED",
                )
        run["resolutions"].update(resolutions)
        at = datetime.now(timezone.utc).isoformat()
        run.setdefault("resolution_actors", {}).update({a: {"by": actor, "at": at} for a in resolutions})
        t["stage"] = "resolved"
        self.store.save(
            t, "human_resolution", {"run_id": run["id"], "resolutions": resolutions, "by": actor, "at": at}
        )
        return t

    def apply(self, id, actor=None):
        from engine.evaluator import POLICY

        t = self.store.get(id)
        assert_contract_integrity(t)
        run = self.latest(t)
        if run["verdicts"] is None:
            raise StateConflictError("Pipeline incomplete: evaluate first", code="STAGE_OUT_OF_ORDER")
        if (
            run.get("apply_result", {})
            and run["apply_result"].get("status") == "APPLIED"
        ):
            raise StateConflictError("Run already applied", code="RUN_ALREADY_APPLIED")
        if t.get("prepared"):
            raise StateConflictError("Unplanned edits exist; create and evaluate a new plan", code="UNPLANNED_EDITS")
        if run.get("policy_hash") != digest(POLICY):
            raise StateConflictError(
                "Policies changed; evaluate again and resolve the new verdicts", code="POLICY_CHANGED"
            )
        with self.vault.unsealed(run["plan_path"]) if run.get("plan_path") else contextlib.nullcontext():
            run["apply_result"] = apply_saved(
                Contract.model_validate(t["contract"]), run, run["resolutions"]
            )
        t["stage"] = run["apply_result"]["status"].lower()
        run["apply_result"]["requested_by"] = actor
        self.store.save(t, "apply_result", run["apply_result"])
        return t

    @staticmethod
    def latest(t):
        if not t["runs"]:
            raise StateConflictError("Pipeline incomplete: no saved plan", code="NO_SAVED_PLAN")
        return t["runs"][-1]
