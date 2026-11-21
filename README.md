# SSH Workspace

Rust-only, local-first SSH companion and MCP tool provider for an existing ChatGPT/Codex session.

**Status:** Development only. No installation or deployment to any user device has been verified. CI artifacts are unsigned development builds, not deployed applications.

## Source

- [Rust native companion](companion/)
- [Native build and test CI](.github/workflows/companion-build.yml)
- [Vault recovery design](docs/VAULT_RECOVERY.md)
- [Contributor and agent instructions](AGENTS.md)

The legacy Python MCP server, Python vault, plugin manifest, and Python CI have been removed from the active repository. Git history retains earlier versions.

## Architecture

The native companion runs on the user's device and connects to explicitly authorized SSH hosts. It integrates only through documented host-managed MCP interfaces. It does not start a second OpenAI model connection or require a separate OpenAI API token. A central SSH gateway is optional, not the default.

SSH is the default transport; Telnet is disabled. Read-only and safe-mode operations are the baseline. Future state-changing commands require device-side authorization and explicit approval. Credentials belong in an encrypted on-device vault; backups must be encrypted before synchronization.

## Current implementation limits

The Rust engine currently provides bounded read-only host-alias, connectivity, OS/architecture, and uptime tools with pinned SSH host-key verification and key/SSH-agent authentication. General shell execution, configuration writes, a Rust encrypted password vault, and native Android/iOS applications are not yet implemented. A stored central gateway endpoint does not imply working transparent forwarding.

## Development

Use the Rust workspace under `companion/` and run its Cargo tests. The native CI builds Windows x64, Linux x64/ARM64, and macOS Intel/Apple Silicon development artifacts. Do not equate a successful CI build with an installed or functioning device plugin.

## Planned native commands

```sh
sshworkspace setup
sshworkspace install --user
sshworkspace host add lab 192.0.2.10 operator 22 /absolute/path/to/ssh-key
sshworkspace doctor
sshworkspace mcp
```

Before connecting to a host, verify and pin its public SSH host key independently.

## Tracking

[Signing](https://github.com/tishriclarin/ssh-workspace/issues/1) · [Pairing/relay](https://github.com/tishriclarin/ssh-workspace/issues/2) · [Android](https://github.com/tishriclarin/ssh-workspace/issues/3) · [iOS](https://github.com/tishriclarin/ssh-workspace/issues/4) · [Permission-controlled operations](https://github.com/tishriclarin/ssh-workspace/issues/5)
