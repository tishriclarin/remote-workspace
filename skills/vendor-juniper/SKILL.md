---
name: vendor-juniper
description: Junos; authorization-first SSH Workspace workflow.
---

# Junos

Only connect to explicitly authorized saved device aliases. Never reveal credentials, keys or host inventory outside the user's authorized scope. A skill describes a workflow; it does not enable a missing transport or grant permissions. Local companion policy and host-key verification remain authoritative.

Use show version, show interfaces terse and show route summary for read-only inspection where supported. Future changes should prefer candidate configs and commit confirmed with rollback deadline. The current native companion does not yet expose generic vendor CLI execution.
