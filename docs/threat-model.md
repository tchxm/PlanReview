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
- A local administrator can rewrite SQLite, policy files, binaries, or the application. Audit is durable, not cryptographically tamper-proof.
- Loopback API is a single-user local tool, not an authenticated multi-tenant service. Do not bind it publicly. Browser origins are checked for mutating requests; this does not authenticate local processes.
- Planning arbitrary Terraform can execute providers or data sources. The optional agent is limited to supplied fixtures, and planning rejects several executable constructs. That guard is not a complete HCL sandbox. Do not connect arbitrary repositories without OS/process isolation and a provider allowlist.
- Global public-access detection currently covers the supplied S3 control and ACL forms, not arbitrary IAM policies or every AWS service. Unsupported types require REVIEW rather than claiming a comprehensive security audit.
- Raw Terraform plans/state can contain secrets even when marked sensitive. Keep `data/` private; only test data belongs in tracked fixtures. Canonical/UI diff redaction does not encrypt raw evidence.
- The same user's files can change between hash verification and subprocess start. Protection against a concurrent privileged local attacker requires a hardened execution service.

## Evidence

`tests/test_gate.py` invokes the gate directly, checks that the subprocess does not spawn, and compares `terraform show -json terraform.tfstate` before and after. A separate local-resource test proves successful execution after approval. The AWS replay does not claim a successful cloud or emulator apply.
