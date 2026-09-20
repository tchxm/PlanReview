# Threat model

## Goal and trusted boundary

Prevent an overreaching Terraform edit from reaching **this application's** apply subprocess without a valid contract and required human decisions. The server, installed Terraform/provider binaries, policy files, local filesystem owner, and confirmation user are trusted. The agent's requested edits and plan values are not approval authority.

## Defenses

- Exact indexed resource identity; no wildcard or index-stripping authorization.
- Unknown or unsupported shapes fail toward REVIEW; explicit known forbidden actions remain DENY.
- Sensitive diffs are redacted and reviewed rather than compared as redacted strings.
- Server-owned saved plans; browser requests cannot supply their own canonical changes or verdicts.
- DENY and unresolved/rejected REVIEW block before subprocess creation.
- Expiry is rechecked at apply, not only at confirmation.
- REVIEW resolutions are bound to a run and discarded for new evaluation/plans.
- Saved binary plan and current Cedar policy hashes are checked at apply.
- Cloud apply is disabled unconditionally; no UI toggle can enable it.
- SQLite audit snapshots keep prior plans, decisions, and application outcomes.

## Explicit exclusions

- An operator can run Terraform directly outside this wrapper. No shell interception or IAM federation is attempted.
- A local administrator can rewrite SQLite, policy files, binaries, or the application. Audit is durable and now hash-chained with a keyed MAC and a local anchor (tamper DETECTION against an attacker without the key; see `docs/audit-integrity.md`). It is not tamper-proof, and a key-holding local attacker can rewrite it.
- (Updated by backend hardening) The API is authenticated with signed, expiring, scoped bearer tokens on top of loopback binding and the Origin check. This defends against other network clients and hostile browser pages. It does NOT defend against another process running as the same OS user, which can read `data/api_secret`, the environment, the SQLite file and the workspaces. It is still a single-user local tool, not a multi-tenant service. Do not bind it publicly. Superseded original text follows: Loopback API is a single-user local tool. Do not bind it publicly. Browser origins are checked for mutating requests; this does not authenticate local processes.
- Planning arbitrary Terraform can execute providers or data sources. The optional agent is limited to supplied fixtures. The pre-plan guard parses `main.tf` as real HCL (top-level blocks limited to terraform/provider/resource, only `required_providers` in `terraform`, no provisioners or connections, resource allowlist) and additionally requires the file to equal the baseline plus exactly the confirmed edit. It is still not a general HCL sandbox. Do not connect arbitrary repositories without OS/process isolation and a provider allowlist.
- Global public-access detection currently covers the supplied S3 control and ACL forms, not arbitrary IAM policies or every AWS service. Unsupported types require REVIEW rather than claiming a comprehensive security audit.
- Raw Terraform plans/state can contain secrets even when marked sensitive. The saved plan, the raw plan JSON and the raw plan copy in the audit log are now **encrypted at rest** (`engine/vault.py`, Fernet, key derived from the API secret; `PLANREVIEW_ENCRYPT_AT_REST=0` disables). Not encrypted: `terraform.tfstate` and `main.tf` (Terraform must read them in place) and the server log. Put `data/` on an encrypted volume, and keep the secret in `PLANREVIEW_API_SECRET` rather than `data/api_secret`, otherwise the key sits next to the ciphertext and this only protects against casual disclosure such as backups or cloud sync of the folder.
- The same user's files can change between hash verification and subprocess start. Protection against a concurrent privileged local attacker requires a hardened execution service.

## Evidence

`tests/test_gate.py` invokes the gate directly, checks that the subprocess does not spawn, and compares `terraform show -json terraform.tfstate` before and after. A separate local-resource test proves successful execution after approval. The AWS replay does not claim a successful cloud or emulator apply.
