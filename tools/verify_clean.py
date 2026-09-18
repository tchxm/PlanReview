"""Verify a source-only export with regenerated plans. Keeps the export for inspection."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    clean = Path(tempfile.mkdtemp(prefix="planreview-clean-")) / "source"
    shutil.copytree(
        ROOT,
        clean,
        ignore=shutil.ignore_patterns(
            ".venv",
            ".git",
            ".terraform",
            ".provider-cache",
            "node_modules",
            "dist",
            "data",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "*.tfstate*",
            "*.tfplan",
        ),
    )
    env = os.environ.copy()
    env["TF_PLUGIN_CACHE_DIR"] = str(ROOT / ".provider-cache")
    records = []
    commands = [
        ([sys.executable, "-u", "terraform/scripts/generate.py"], clean),
        ([sys.executable, "-m", "pytest", "-q"], clean),
        (["npm.cmd" if os.name == "nt" else "npm", "ci"], clean / "web"),
        (["npm.cmd" if os.name == "nt" else "npm", "run", "build"], clean / "web"),
    ]
    for command, cwd in commands:
        print("RUN", command, "IN", cwd, flush=True)
        p = subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, timeout=900
        )
        print(p.stdout, flush=True)
        print(p.stderr, flush=True)
        records.append(
            {
                "command": command,
                "cwd": str(cwd),
                "exit_code": p.returncode,
                "stdout": p.stdout,
                "stderr": p.stderr,
            }
        )
        (ROOT / "docs/evidence/clean-build.json").write_text(
            json.dumps({"source_export": str(clean), "commands": records}, indent=2)
        )
        if p.returncode:
            raise SystemExit(p.returncode)
    print("CLEAN SOURCE VERIFICATION PASSED", clean, flush=True)


if __name__ == "__main__":
    main()
