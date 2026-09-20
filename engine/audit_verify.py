"""Verify the audit chain from the command line.

  python -m engine.audit_verify                      # local anchor
  python -m engine.audit_verify --anchor D:\usb\anchor.json   # an exported anchor
  python -m engine.audit_verify --export D:\usb\anchor.json   # export the current anchor

Exit code 0 = no tampering detected, 1 = problems found.
"""

import argparse
import json
import sys
from pathlib import Path

from engine import auth
from engine.storage import Store, derive_audit_key

ap = argparse.ArgumentParser()
ap.add_argument("--data", default=str(Path(__file__).resolve().parents[1] / "data"))
ap.add_argument("--anchor", default=None)
ap.add_argument("--export", default=None)
a = ap.parse_args()
store = Store(Path(a.data) / "planreview.sqlite", key=derive_audit_key(auth.load_secret(a.data)))
if a.export:
    print(json.dumps(store.export_anchor(a.export)))
    sys.exit(0)
result = store.verify_audit(a.anchor)
print(json.dumps(result, indent=2))
sys.exit(0 if result["ok"] else 1)
