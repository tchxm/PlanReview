# Demo script

1. Start the compiled console with `./start.ps1` and visit `http://localhost:8000`.
2. Create a task in **Local fixture replay** mode. Explain that these are real Terraform plans from deterministic edits; no live model is running.
3. On Confirm Contract, choose **Use three-color demo scope**, inspect the production/public-access forbids and three-resource cap, then confirm. Networking is deliberately uncovered, so it receives REVIEW. A strict networking forbid would produce DENY.
4. Run the poisoned fixture. The Lambda memory diff is 512 → 1024 (ALLOW), the SG adds internal HTTPS ingress (REVIEW), and four S3 public-access protections change true → false (DENY).
5. Show the refused Apply button and use **Verify block via API**. The server records `spawned: false` and the explicit DENY reason.
6. Open Resolution. Show that only REVIEW has an approval selector. Re-plan without S3 changes, then approve the fresh SG REVIEW. Approvals from the previous plan do not carry over.
7. Attempt apply again. It remains blocked by the environment's unconditional AWS-apply restriction. Do not describe this as a successful AWS apply.
8. Open Audit, inspect stored confirmation, raw plan, canonical changes, verdicts, resolutions, and apply result. Export the audit JSON if needed.
9. For successful process execution, run `.venv/Scripts/python.exe -m pytest -q tests/test_gate.py::test_real_local_apply`. Show `docs/evidence/local-apply.json`, including the actual apply stdout and state output.

For a two-prompt command-line replay use `./run-demo.sh` or `./run-demo.ps1`. `--scripted` / `-Scripted` explicitly labels demo automation, not human consent. Live Strands and full AWS-emulator completion remain follow-up environment work recorded in STATUS.md.
