---
name: ssh-client
description: Native SSH protocol workflows; authorization-first Remote Workspace workflow.
---

# Native SSH protocol workflows

Only connect to explicitly authorized saved device aliases. Never reveal credentials, keys or host inventory outside the user's authorized scope. A skill describes a workflow; it does not enable a missing transport or grant permissions. Local companion policy and host-key verification remain authoritative.

SSH is the default secure protocol. Verify pinned host keys before authentication, inspect platform capabilities, use read-only diagnostics where available, and require local approval for future write operations. Prefer SSH certificates/agent identities or OS-keystore references; do not embed passwords in skill text.

**Mandatory prerequisite:** load `../remote-safety/SKILL.md` and `../remote-workspace/SKILL.md`. Unregistered devices are read-only. Registered devices may be edited only after verified backup, explicit permission and enforced device-side approval; current SSH tools do not implement writes.
