# Remote Workspace

Rust-only, local-first SSH companion and MCP tool provider for an existing ChatGPT/Codex session.

**Status:** Development only. No installation or deployment to any user device has been verified. CI artifacts are unsigned development builds, not deployed applications.

## Source

- [Rust native companion](companion/)
- [Native build and test CI](.github/workflows/companion-build.yml)
- [Vault recovery design](docs/VAULT_RECOVERY.md)
- [Contributor and agent instructions](AGENTS.md)

The legacy Python MCP server, Python vault, plugin manifest, and Python CI have been removed from the active repository. Git history retains earlier versions.

## Architecture

The native companion runs on the user's device and connects to explicitly authorized SSH hosts. For global ChatGPT distribution, the plugin connects to a stable, publicly reachable HTTPS Rust MCP gateway; users pair an independently installed OS-specific Rust companion, which initiates outbound connections and keeps SSH credentials local. The gateway authenticates and routes tool requests to paired companions. Desktop-local stdio MCP remains a separate development option, not the global mobile plugin. No second OpenAI model connection or separate model API token is required.

SSH is the default transport; Telnet is disabled. Read-only and safe-mode operations are the baseline. Future state-changing commands require device-side authorization and explicit approval. Credentials belong in an encrypted on-device vault; backups must be encrypted before synchronization.

## Current implementation limits

The Rust engine currently provides bounded read-only host-alias, connectivity, OS/architecture, and uptime tools with pinned SSH host-key verification and key/SSH-agent authentication. General shell execution, configuration writes, a Rust encrypted password vault, and native Android/iOS applications are not yet implemented. The public HTTPS gateway, authenticated pairing, and companion forwarding are not implemented yet; configuration alone does not establish connectivity.

## Global plugin distribution (official OpenAI MCP model)

Publish **one small plugin** with a remote MCP server URL using Streamable HTTP at a stable public HTTPS `/mcp` endpoint. The ChatGPT plugin package contains only skills, metadata, and MCP connection configuration, **no native binaries**. Public remote MCP submission requires developer review, server availability, and suitable authentication (OAuth for user identity; mTLS can authenticate ChatGPT). Device-specific Rust companions are distributed separately through OS-approved channels and paired explicitly. The gateway never stores device SSH private keys. The companion makes outbound authenticated connections; the server verifies per-user, per-device and per-tool authorization and requires device approval for changes. Android/iOS require native apps and OS-supported background execution. This architecture is the release target, not a claim that the remote server or mobile apps exist today.

Official references: [plugin architecture](https://developers.openai.com/plugins/concepts/plugins), [MCP server deployment](https://developers.openai.com/plugins/build/mcp-server), [remote review](https://developers.openai.com/plugins/deploy/app-review), [authentication](https://developers.openai.com/plugins/build/auth).

## Development

Use the Rust workspace under `companion/` and run its Cargo tests. The native CI builds Windows x64, Linux x64/ARM64, and macOS Intel/Apple Silicon development artifacts. Do not equate a successful CI build with an installed or functioning device plugin.

## Planned native commands

```sh
remoteworkspace setup
remoteworkspace install --user
remoteworkspace host add lab 192.0.2.10 operator 22 /absolute/path/to/ssh-key
remoteworkspace doctor
remoteworkspace mcp
```

Before connecting to a host, verify and pin its public SSH host key independently.

## Tracking

[Signing](https://github.com/tishriclarin/remote-workspace/issues/1) · [Pairing/relay](https://github.com/tishriclarin/remote-workspace/issues/2) · [Android](https://github.com/tishriclarin/remote-workspace/issues/3) · [iOS](https://github.com/tishriclarin/remote-workspace/issues/4) · [Permission-controlled operations](https://github.com/tishriclarin/remote-workspace/issues/5)
