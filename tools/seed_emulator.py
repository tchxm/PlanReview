"""Create the baseline infrastructure (dev-api Lambda, assets bucket, security group) inside the loopback emulator,
so a permitted plan has something real to modify. Same steps as tests/test_emulator_apply.py."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def seed(emu, plugin_cache=None, timeout=900):
    env = {**os.environ, **emu.env(), "TF_PLUGIN_CACHE_DIR": str(plugin_cache or os.environ.get("PLANREVIEW_PLUGIN_CACHE") or ROOT / ".provider-cache")}
    Path(env["TF_PLUGIN_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="planbound-baseline-"))
    for n in ["lambda.zip", ".terraform.lock.hcl", "main.tf"]:
        src = ROOT / "terraform/fixtures/baseline" / n
        if src.exists():
            shutil.copy2(src, base / n)
    for args in (["init", "-input=false", "-no-color"], ["apply", "-auto-approve", "-input=false", "-no-color"]):
        r = subprocess.run(["terraform", *args], cwd=base, env=env, capture_output=True, text=True, timeout=timeout)
        if r.returncode:
            raise RuntimeError("terraform %s failed while seeding the emulator: %s" % (args[0], (r.stdout + r.stderr)[-600:]))
