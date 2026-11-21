---
name: vendor-zte
description: ZTE OLT; authorization-first SSH Workspace workflow.
---

# ZTE OLT

Only connect to explicitly authorized saved device aliases. Never reveal credentials, keys or host inventory outside the user's authorized scope. A skill describes a workflow; it does not enable a missing transport or grant permissions. Local companion policy and host-key verification remain authoritative.

Identify ZTE OLT model and CLI mode, PON/ONU layout, and interface privilege level. Use approved version-specific read-only show commands after capability detection. Provisioning, VLAN, ONU and reboot changes require explicit approval and safe rollback; never apply generic bulk templates blindly.
