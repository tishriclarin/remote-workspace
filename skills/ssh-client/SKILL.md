---
name: ssh-client
description: Native SSH protocol workflows; authorization-first SSH Workspace workflow.
---

# Native SSH protocol workflows

Only connect to explicitly authorized saved device aliases. Never reveal credentials, keys or host inventory outside the user's authorized scope. A skill describes a workflow; it does not enable a missing transport or grant permissions. Local companion policy and host-key verification remain authoritative.

SSH is the default secure protocol. Verify pinned host keys before authentication, inspect platform capabilities, use read-only diagnostics where available, and require local approval for future write operations. Prefer SSH certificates/agent identities or OS-keystore references; do not embed passwords in skill text.
