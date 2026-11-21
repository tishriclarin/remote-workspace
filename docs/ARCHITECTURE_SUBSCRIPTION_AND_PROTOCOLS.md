# Architecture decision: subscription reuse and device-side protocols

**Decision date:** 2026-11-21. **Status:** adopted design; deployment varies by ChatGPT platform.

## Non-negotiable behavior
SSH Workspace is a ChatGPT/Codex **tool provider**, not an OpenAI model client. It does **not** invoke billable OpenAI Responses/Chat Completions APIs, store ChatGPT session tokens, or request a second model subscription. Tool calls and results appear within the user's existing ChatGPT conversation.

The current ChatGPT subscription securely authenticates *ChatGPT*, but it does not grant third-party software a documented right to intercept the browser WebSocket/TLS session or execute native code. Reuse supported **host-managed local MCP execution** where available (desktop local thread), or a registered **HTTPS MCP tool endpoint** (web). The web tool endpoint might route to a companion over an authenticated outbound connection; this is a separate network transport and need not involve paid OpenAI model tokens. Web tool relay and native mobile apps are **not yet implemented**. No hijacking session cookies or private chat sockets.

## Components
1. Existing ChatGPT or Codex chat, model and authentication. The host invokes approved MCP tools.
2. Portable ChatGPT plugin exposing safe tools and skills. It performs no independent model inference.
3. Rust companion on the user's machine or phone. It validates commands, host permissions, network destination, host identity, and approval decisions.
4. Encrypted host vault: account, IP/DNS, port, SSH certificate/key reference, host-key pin, per-device safe/read-only policy, protocol and vendor. See [schema](../config/host-profile.schema.json).
5. Pluggable **protocol engines**. SSHv2 is implemented for diagnostics; Telnet is disabled and unimplemented, with explicit insecure-transport authorization required before any future support.
6. Pluggable **vendor skills**. MikroTik, Cisco, Juniper, Huawei, ZTE and other platform instructions may be added without widening protocol permission. Skills are not an authorization mechanism.
7. Backup provider: local directory (default); encrypted export into a user-controlled cloud-sync folder (optional). Direct cloud APIs are future adapters; never upload an encryption key with ciphertext.

## Connection mode semantics
- **local**: host-managed stdio MCP on approved desktop surfaces; no API key, no tunnel, no extra model billing.
- **web**: ChatGPT invokes registered HTTPS Streamable HTTP MCP endpoint. The relay forwards only authenticated MCP tool messages/results to a companion. It must never run its own OpenAI model calls. An explicit per-user pairing is needed.
- **central**: explicit user choice for a hosted SSH gateway. Never enabled as a silent fallback.
- **unsupported host**: explain limitations; do not fabricate a local bridge or silently install software.

## Access control and vault requirements
- Default per-host policy: read-only and safe mode, write operations approval-required.
- Certificate and password material kept in OS credential store or locally encrypted vault, not chat or GitHub.
- SSH host-key verification is mandatory; unknown/changed keys rejected.
- Cloud backups must be encrypted **before** upload. Backups carry no plaintext secrets; recovery key is protected separately.
- Host selection and connection authorization must be enforced by local companion, not by language-model instructions.
- Device operations must be audited without secrets.
- A protocol plugin cannot bypass safe mode or the host allowlist.
- Telnet: no automatic SSH fallback, disabled by default, isolated network warning and opt-in if implemented.

## Platform truth
Official [ChatGPT desktop-only plugin](https://developers.openai.com/plugins/deploy/desktop-only) supports local stdio MCP under eligibility/approval. Official [remote MCP plugin](https://developers.openai.com/plugins/build/mcp-server) uses stable HTTPS and Streamable HTTP for public web connections. [ChatGPT/API billing](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform) is separate; SSH Workspace must not call a billed model API.

## Delivery milestones
- Portable root plugin.json and mcp.json plus vendor skills in desktop package.
- Encrypted host vault and encrypted local/cloud-sync backups.
- Real device access-policy enforcement and vendor engine adapters.
- Optional user-owned web endpoint/pairing, with no OpenAI model API.
- Mobile companion distribution compliant with Android/iOS policies.
