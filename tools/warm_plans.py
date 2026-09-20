"""Build-time helper for hosted deploys: run the real pipeline up to `terraform plan` for the demo agent variants so
engine/pipeline.py can reuse the real plan output at runtime. Usage: python tools/warm_plans.py (after install_terraform.py)"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "bin").exists():
    os.environ["PATH"] = str(ROOT / "bin") + os.pathsep + os.environ["PATH"]
os.environ["PLANREVIEW_TF_TIMEOUT"] = "900"
os.environ["PLANREVIEW_DATA_DIR"] = tempfile.mkdtemp(prefix="warm-")

from engine.pipeline import Pipeline  # noqa: E402

TASK = "Increase memory for dev-api Lambda; send unanticipated networking changes to human review. Production and public access are forbidden."


def main():
    p = Pipeline()
    for variant in ("intended", "poisoned"):
        t = p.create(TASK)
        p.confirm(t["id"])
        p.agent(t["id"], variant)
        p.plan(t["id"])
        print("cached real plan for", variant)


main()
