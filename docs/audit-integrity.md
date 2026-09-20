# Audit integrity: what is and is not claimed

The audit log is a table of events in the local SQLite file. Since this hardening each new event also carries `prev` and `mac`:

```
mac = HMAC-SHA256(audit_key, prev | id | task_id | timestamp | kind | body)
```

`prev` is the previous event's `mac` (a single chain across all tasks; the first is `0…0`). `audit_key` is derived from the server secret (`PLANREVIEW_API_SECRET` or `data/api_secret`), domain-separated from the API signing use. Each save runs in one `BEGIN IMMEDIATE` transaction, so the chain stays consistent even with concurrent writers. After every save the head `{head_id, head_mac, protected_events}` is atomically written to `data/audit_anchor.json`.

## Four different things

| Property | Status | Meaning here |
|---|---|---|
| **Append-only application behaviour** | Yes | The API and pipeline only ever INSERT events; nothing in the code updates or deletes them. This is a property of our code, not of the file. |
| **Tamper detection** | Yes, against an attacker WITHOUT the key | Editing a row, deleting a row (middle or tail), inserting a forged row, reordering rows, deleting a task row, or rewriting the confirmed-contract hash in the `tasks` table is reported by `GET /api/audit/verify` (needs the `evidence` scope) or `python -m engine.audit_verify`. Tail truncation and whole-database replacement are caught by the anchor. |
| **Tamper resistance** | **No** | Nothing stops a process with write access from changing the file. SQLite has no write protection here. |
| **Protection against a compromised machine owner** | **No** | Any process running as the same OS user can read the key file (`data/api_secret`) or the environment, then rewrite events, recompute the chain and rewrite the local anchor consistently. The test `test_attacker_WITH_the_key_can_rewrite_everything_local_anchor_included` demonstrates exactly this and passes on purpose. |

## The only external defence: an exported anchor

`python -m engine.audit_verify --export <path>` copies the current anchor. If that copy lives somewhere the database's writer cannot modify (another machine, removable or write-once media, a separate account), then `--anchor <path>` verification catches a key-holding rewrite of history **up to the exported point**: the exported head's `mac` will not match the forged chain (`ANCHOR_MISMATCH`). It gives no protection for events written after the export. Exporting regularly and off-box is the operator's responsibility; the application does not do it.

## Other limits

- Rows written before this change have no MAC. They are reported as `unprotected_legacy_events` and are not trusted or verified.
- Rotating the server secret makes every existing MAC fail verification. Keep the secret stable or export an anchor first and treat the old log as archived.
- `confirmed_contract_hash` in a task is still an unkeyed SHA-256 (it detects accidental or naive edits). Deliberate rewriting of it is caught only through the cross-check against the keyed `human_confirmation` audit record.
- The chain is not a timestamp authority; timestamps come from the local clock.

**Do not describe this log as tamper-proof.** It is tamper-evident against an attacker who lacks the key, with an optional external anchor to extend that to a key-holding attacker for history before the export.
