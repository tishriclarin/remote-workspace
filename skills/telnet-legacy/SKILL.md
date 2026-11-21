---
name: telnet-legacy
description: Legacy insecure Telnet (disabled); authorization-first SSH Workspace workflow.
---

# Legacy insecure Telnet (disabled)

Only connect to explicitly authorized saved device aliases. Never reveal credentials, keys or host inventory outside the user's authorized scope. A skill describes a workflow; it does not enable a missing transport or grant permissions. Local companion policy and host-key verification remain authoritative.

Telnet has no native transport encryption and can expose credentials in transit. The Telnet driver is NOT implemented and is DISABLED by default. A future operator-enabled implementation must require per-host allowlists, isolated networks, explicit insecure-transport warnings, policy checks and no credentials across untrusted networks. Never silently fall back from SSH to Telnet.
