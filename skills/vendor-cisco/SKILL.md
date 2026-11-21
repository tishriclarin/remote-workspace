---
name: vendor-cisco
description: Cisco IOS, IOS-XE and NX-OS; authorization-first SSH Workspace workflow.
---

# Cisco IOS, IOS-XE and NX-OS

Only connect to explicitly authorized saved device aliases. Never reveal credentials, keys or host inventory outside the user's authorized scope. A skill describes a workflow; it does not enable a missing transport or grant permissions. Local companion policy and host-key verification remain authoritative.

Detect IOS family before selecting commands. Examples: show version; show interfaces status where supported; show ip route summary. Future changes need privilege validation, config backup, change preview, explicit authorization, verification and rollback. Never assume IOS and NX-OS syntax identical.
