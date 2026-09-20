"""One command: PlanBound site + API + real pipeline + local AWS emulator.  python run_site.py  ->  http://127.0.0.1:8000/

- Starts the loopback moto emulator (dummy credentials, 127.0.0.1 only) so a PERMITTED plan really applies to it.
  Nothing here can reach a real AWS account. Set PLANBOUND_EMULATOR=0 to skip it (apply then reports BLOCKED).
- Keeps Terraform's workspaces and provider cache OUTSIDE OneDrive (huge, and syncing makes terraform crawl).
  Override with PLANREVIEW_DATA_DIR / PLANREVIEW_PLUGIN_CACHE.
"""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
home = Path.home() / ".planbound"
if "OneDrive" in str(ROOT):
    os.environ.setdefault("PLANREVIEW_DATA_DIR", str(home / "data"))
    os.environ.setdefault("PLANREVIEW_PLUGIN_CACHE", str(home / "plugins"))
    cache = Path(os.environ["PLANREVIEW_PLUGIN_CACHE"])
    if not cache.exists() and (ROOT / ".provider-cache").exists():
        print("Copying the Terraform provider cache out of OneDrive (once)...")
        shutil.copytree(ROOT / ".provider-cache", cache)

os.environ.setdefault("PLANREVIEW_TF_TIMEOUT", "900")  # first Terraform runs on Windows can be slow
if (ROOT / "bin").exists():  # hosted builds put the Terraform CLI here (tools/install_terraform.py)
    os.environ["PATH"] = str(ROOT / "bin") + os.pathsep + os.environ["PATH"]
if os.environ.get("PLANBOUND_EMULATOR") != "0":
    try:
        from tools.emulator import Emulator

        emu = Emulator().start()
        os.environ.update(emu.env())
        print("Local AWS emulator on", emu.endpoint, "(loopback, dummy credentials)")
        if shutil.which("terraform"):
            from tools.seed_emulator import seed

            print("Seeding the emulator with the baseline infrastructure (dev-api Lambda, assets bucket, security group)...")
            seed(emu)
    except Exception as e:  # moto missing etc.: the site still works, apply reports BLOCKED
        print("Emulator not started:", e)

import uvicorn  # noqa: E402

uvicorn.run("engine.api:app", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
