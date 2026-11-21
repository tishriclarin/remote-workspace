---
name: vendor-mikrotik
description: MikroTik RouterOS; authorization-first SSH Workspace workflow.
---

# MikroTik RouterOS

Only connect to explicitly authorized saved device aliases. Never reveal credentials, keys or host inventory outside the user's authorized scope. A skill describes a workflow; it does not enable a missing transport or grant permissions. Local companion policy and host-key verification remain authoritative.

Detect RouterOS release and privileges. Example read-only checks: /system resource print; /interface print terse; /ip route print. For future writes, use RouterOS Safe Mode where available, take backups and previews, obtain explicit approval and verify rollback. These are NOT currently executable through generic native MCP tools.
