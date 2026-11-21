# Remote Workspace device authorization policy

This project is currently named Remote Workspace. Future product name: **Remote Workspace**. Preserve existing binary and package names until an explicit, tested migration; design policy independently of transport.

## Immutable security defaults

- Unknown or unregistered target: read-only, no configuration changes.
- Registered target: read-only unless a separately granted write capability exists.
- Every authorized write requires a fresh verified backup and explicit approval scoped to device, commands and expiry.
- Failure of identity verification, backup, approval, authorization, connectivity or policy evaluation: deny.
- Policy applies to AI requests and direct API callers; prompts are not enforcement.
- Credentials, secrets, backup encryption keys and authorization tokens must never be returned in MCP responses.
- Backups must be recoverable, encrypted at rest, integrity-checked and tied to the target's stable identity. If backup is impossible, refuse the write.
- Prevent concurrent conflicting changes, log audit events, and limit privileges to the least required scope.

## Sample policy data

```json
{
  "schema_version": 1,
  "default": {
    "registered": false,
    "mode": "read_only",
    "backup_before_change": true,
    "require_explicit_approval": true
  },
  "devices": {
    "site-router-01": {
      "registered": true,
      "identity_fingerprint": "REPLACE_WITH_VERIFIED_FINGERPRINT",
      "mode": "approval_required",
      "allowed_operations": ["config_edit"],
      "backup_before_change": true,
      "require_explicit_approval": true
    }
  }
}
```

The sample is documentation, **not an enabled write permission**. Current Rust companion and gateway expose only read-only diagnostics. A future implementation must validate policy and approval on the companion, not merely load this JSON.

## Required change lifecycle

DISCOVER → VERIFY IDENTITY → CHECK REGISTRATION → CHECK CAPABILITY → BACKUP → VERIFY RESTORE MATERIAL → PRESENT DIFF/IMPACT → EXPLICIT APPROVAL → REVALIDATE → EXECUTE → VERIFY → AUDIT.

A failed stage must not proceed to the next stage.
