# SSH Workspace — Standing implementation instructions

These are the owner's persistent implementation and communication preferences for contributors, coding agents, and scheduled automation. Apply them in subsequent work on this repository.

## Execution-first operating mode

- Implement the request directly when authorized and technically possible. Do not turn a concrete build request into repeated proposals, reassurances, or generic warnings.
- If uncertain whether an implementation works, inspect official interfaces, create a small reproducible test, run it, and follow the results. Prefer verification to speculation.
- Report actual results: code changes, commit IDs, build/test outcomes, installations, and specific next actionable failures. Never assert untested success.
- Surface a blocker only if it is concrete and materially prevents the requested step. State what was tested and which interface rejected it; do not repeat the same limitation at each turn.
- Never claim that a chat turn keeps working indefinitely after it ends. Use already-authorized scheduled automation and CI for independent work.
- Keep responses concise, technical, and free of patronizing language. No unnecessary clarifying questions when the repository and the owner's existing requirements supply the answer.
- Avoid extra tangents and unrelated projects. Focus this repository and its development tasks exclusively on SSH Workspace.

## Core product constraints

- This is a plugin/tool provider for the user's existing ChatGPT/Codex experience, **not** a separate ChatGPT client.
- Never instantiate another billable OpenAI model API connection or request separate API-token payment to implement local SSH functionality. Prefer documented host-managed MCP invocation with the existing ChatGPT experience.
- Do not claim private ChatGPT session traffic or authentication tokens are a supported device-execution API. If a platform lacks a documented local tool channel, test its actual supported extension points; do not hijack cookies, channels, or protocols.
- The native companion implements device-side SSH and authorization. SSH is the default encrypted protocol; vendor-specific skills are modular and never elevate permissions.
- Keep credentials and device inventory in the locally encrypted vault. Backups must be encrypted before cloud synchronization. The central SSH gateway is optional.
- Telnet or other weaker protocols may be added only as explicit opt-in, isolated, auditable modules; never silently downgrade from SSH.
- Default to read-only and safe mode; any state-changing device command must have an explicit authorization/approval mechanism enforced by the native companion.

## Definition of done

- Update the existing `tishriclarin/ssh-workspace` repository instead of producing documentation-only plans when implementation is possible.
- Add tests for new functionality, exercise them in CI, fix compiler/runtime failures, and inspect actual workflow results.
- Do not call an Android plugin installer, signed release, pairing mechanism, or end-to-end SSH operation complete until the corresponding artifact and integration have been tested.
- When a platform does not expose the required API, retain the user's goal and validate supported integration points; do not fabricate one.
- Summarize actionable progress and any true remaining blockers without speculative warnings.

These preferences are project guidance, not a claim that a repository can modify the global ChatGPT model or guarantee memory retention forever.

## Rust-only baseline (November 2026)

- The project has never been deployed to any user device; CI builds are not deployments.
- Rust is the sole supported application implementation. Do not restore or maintain the legacy Python server, vault, launcher, or Python packaging pipeline.
- Prioritize implementing and testing the native Rust companion, MCP interface, and security boundaries. Use Cargo tests and native CI, not Python regression workflows.
- For clearly authorized repository cleanup, execute and commit safe changes rather than requesting repeated confirmation. Git history is the recovery mechanism.

## Mandatory remote-device safety rules

- Load `skills/remote-safety/SKILL.md` and `skills/remote-workspace/SKILL.md` before any remote-device operation; all vendor and protocol skills inherit these restrictions.
- Unregistered or identity-unverified devices are strictly read-only. Registration never implicitly authorizes writes.
- For registered devices, require a fresh verified restorable backup, explicit device-specific write permission, exact command preview, and a fresh approval before any change.
- Native Rust policy enforcement is mandatory: prompt instructions and skills cannot substitute for a device-side authorization gate. Deny all writes until this gate is implemented and tested.
- The planned product name is Remote Workspace; preserve SSH Workspace names and compatibility until a deliberate versioned migration. Build protocol-neutral safety rules for future adapters.
