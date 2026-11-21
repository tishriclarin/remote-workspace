# SSH Workspace 0.7.0 — native companion

This directory introduces a **native Rust SSH + MCP engine** alongside the existing Python desktop plugin. Local-first means the device running the companion initiates SSH and holds authentication material. The centralized HTTPS MCP gateway remains an **optional** setting. The companion is not a centralized SSH proxy.

## Current implementation

- Self-contained Rust CLI/MCP executable using an embedded libssh2 SSH engine. No external OpenSSH or Python runtime required for these new diagnostic tools.
- Defaults to `client` mode. `central` is an explicit configuration choice.
- Strict host-key pinning against an existing OpenSSH `known_hosts` file; unknown or changed keys are rejected.
- Authentication using a local private key file or SSH agent. Password storage is **not yet implemented** in the Rust binary; the existing Python vault remains available for legacy desktop deployments.
- Six read-only MCP tools: gateway status, installation guidance, host aliases, connectivity, OS/CPU, uptime.
- Browser Native Messaging accepts **status and installation guidance only**. It cannot execute SSH commands and requires an explicitly installed and ID-restricted browser extension.
- GitHub Actions packages a desktop plugin ZIP and builds reviewable **unsigned** artifacts for Linux x64/ARM64, Windows x64 and macOS Intel/Apple Silicon. Actual runner availability and build results must be checked.

## Local use

```sh
cd companion
cargo build --release
./target/release/sshworkspace setup
./target/release/sshworkspace host add lab 192.0.2.10 operator 22 ~/.ssh/id_ed25519
./target/release/sshworkspace doctor
./target/release/sshworkspace mcp
```

Replace example host and username with an authorized system, and independently verify its SSH host-key fingerprint before adding an entry to `~/.ssh/known_hosts`. Do **not** blindly trust an `ssh-keyscan` result. The program never disables strict host-key checks.

By default settings and host aliases are stored in the current user's SSH Workspace configuration directory (Windows `%APPDATA%\\ssh-workspace`, macOS `~/Library/Application Support/ssh-workspace`, Linux `~/.config/ssh-workspace`). Set `SSHWORKSPACE_HOME` to override. Unix config files are owner-only.

## Gateway options

```sh
sshworkspace gateway client
sshworkspace gateway central https://your-domain.example/mcp
sshworkspace status
```

Central mode records the HTTPS endpoint but **does not implement transparent remote forwarding**. To use a centralized gateway, register that server's MCP endpoint through ChatGPT's supported connection flow.

## Installation experience

Desktop users can download a verified binary artifact once the GitHub Actions build succeeds, then approve its execution/installation. A future signed installer can register local MCP and browser native messaging on the user's behalf where OS and browser rules permit. We do not silently install browser extensions, native applications or mobile apps.

**ChatGPT browser and native mobile restrictions:** Web ChatGPT cannot automatically attach to a binary running on its user's computer or phone. A supported secure MCP tunnel or paired relay is still necessary. A full browser extension with native-host registration, signed Android application, signed iOS application, and production tunnel integration are **not shipped** here. Browser-native SSH is not a generally available API.

The native companion is designed to support these later integrations without moving SSH private keys to a central service.

## Chromium extension preview

Optional status-only extension sources are in [browser/chromium](../browser/chromium/README.md). Install it with browser approval and register its exact extension ID using the native binary. This is not a ChatGPT MCP tunnel.

## Security boundaries

- No generic `run_command`, terminal, credential reveal, or unsafe tool; fixed, bounded diagnostic commands only.
- Local SSH and host-key verification are performed by this binary, not by ChatGPT.
- Agent key or private key file remains local; no password database is created.
- Do not run the native messaging helper on an unrestricted browser extension origin.
- User/admin changes and software installation require approval; existing read-only diagnostics need not prompt repeatedly.
- Signed, notarized installers and app-store approval are separate release tasks.
- Avoid publishing a public release before test, code-signing and security review.

## CI and verification

Run `cargo test` and `cargo build --release`. GitHub Actions artifacts include a desktop-only plugin ZIP generated from the native binary and checked by MCP smoke tests; these are unsigned CI products, **not verified installers**. See [workflow](../.github/workflows/companion-build.yml).

## Supported private ChatGPT tunnel (developer connection)

The official OpenAI Secure MCP Tunnel client supports stdio MCP targets. SSH Workspace now provides a small convenience CLI that creates a dedicated profile for the currently installed Rust companion. It uses only the installed, official tunnel-client executable and does not ask for or write API keys itself.

1. Obtain the supported tunnel-client and a tunnel ID from https://platform.openai.com/settings/organization/tunnels.
2. Provide CONTROL_PLANE_API_KEY through the runtime's secure environment or system secret storage; never paste it into ChatGPT.
3. Run SSH Workspace commands shown below.

    sshworkspace tunnel init tunnel_0123456789abcdef0123456789abcdef
    sshworkspace tunnel doctor
    sshworkspace tunnel run

The last command intentionally runs in the foreground. Tunnel credentials and authorization remain managed by OpenAI's official client. The local gateway still initiates every SSH connection. This private tunnel option does not meet the stable public endpoint requirement for a publicly published remote-MCP plugin.

## Self-contained desktop installation

After downloading and approving the appropriate native executable, run sshworkspace install --user once. It copies itself atomically to a per-user private application directory without root/admin privileges or third-party dependencies. The command does not silently modify your PATH or install a browser extension. Run sshworkspace register-chrome EXTENSION_ID only after the browser extension has been approved. OS signing and production auto-update remain pending.
