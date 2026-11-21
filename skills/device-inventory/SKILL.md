---
name: device-inventory
description: Device accounts, ports and certificates; authorization-first SSH Workspace workflow.
---

# Device accounts, ports and certificates

Only connect to explicitly authorized saved device aliases. Never reveal credentials, keys or host inventory outside the user's authorized scope. A skill describes a workflow; it does not enable a missing transport or grant permissions. Local companion policy and host-key verification remain authoritative.

Maintain device aliases, addresses or DNS names, ports, vendor labels, usernames, SSH identity and certificate references, known-hosts path, groups and permission policies. Host profiles and credentials belong in the encrypted local vault. Backups must be encrypted before leaving the device. The v1 schema is an implementation target.
