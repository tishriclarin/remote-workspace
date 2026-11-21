# SSH Workspace 0.7.0 — native companion

This directory introduces a **native Rust SSH + MCP engine** as the sole supported application implementation. Local-first means the device running the companion initiates SSH and holds authentication material. The centralized HTTPS MCP gateway remains an **optional** setting. The companion is not a centralized SSH proxy.

## Connection routing: reuse the existing ChatGPT session by default

**Local mode is host-managed.** When a supported ChatGPT desktop/local thread exposes a local MCP executor, ChatGPT invokes the bundled Rust companion as an MCP tool over stdio. This reuses the host's normal authenticated ChatGPT session and authorized MCP routing; it does **not** require an OpenAI API key, a second sign-in, a public HTTP server or an MCP tunnel. SSH commands originate on the user's device and return as normal tool results.

**Transport boundary:** ChatGPT's normal HTTPS connection is secure, but its chat transport cannot be intercepted or turned into an arbitrary native command channel. Only use the host's documented MCP tool invocation capabilities. If a web or mobile ChatGPT client does not expose a local MCP execution channel, the plugin cannot silently reuse its chat socket to reach the user's companion. In such environments, show an explicit unsupported state or offer user-approved remote/tunnel transport. Never pretend that merely being signed into ChatGPT authorizes arbitrary device operations.

A centralized SSH gateway is always optional. Secure MCP Tunnel is an opt-in fallback for supported private workflows and not part of the local desktop default. Store SSH secrets locally and enforce local per-host authorization and safe/read-only behavior irrespective of ChatGPT authentication.

## Current implementation

- Self-contained Rust CLI/MCP executable using an embedded libssh2 SSH engine. No external OpenSSH or Python runtime required for these new diagnostic tools.
- Defaults to `client` mode. `central` is an explicit configuration choice.
- Strict host-key pinning against an existing OpenSSH `known_hosts` file; unknown or changed keys are rejected.
- Authentication using a local private key file or SSH agent. Password storage is **not yet implemented** in the Rust binary; there is no Python fallback.
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

**ChatGPT browser and native mobile restrictions:** Web ChatGPT cannot automatically attach to a binary running on its user's computer or phone. Local execution through the current ChatGPT session is possible only when the host explicitly supports that MCP capability; otherwise a separate user-approved transport is required. A full browser extension with native-host registration, signed Android application, signed iOS application, and production tunnel integration are **not shipped** here. Browser-native SSH is not a generally available API.

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

## Encrypted host vault and backups

New companion installations store authorized host records in `hosts.vault`, encrypted with **XChaCha20-Poly1305**. A random local 256-bit key is held separately in `vault.key` with owner-only permissions where supported. SSH account metadata, host addresses, ports and SSH key/certificate references are encrypted in the inventory. Private SSH key files themselves remain externally managed. **OS keychain wrapping and passwords are planned, not yet available.**

Commands:

    sshworkspace setup
    sshworkspace vault status
    sshworkspace vault migrate
    sshworkspace backup configure local ~/sshworkspace-backups
    sshworkspace backup configure cloud-sync ~/MyCloudSync/sshworkspace-backups
    sshworkspace backup run "before router upgrade"
    sshworkspace backup status
    sshworkspace backup restore ~/sshworkspace-backups/sshworkspace-example.vault --confirm

The cloud-sync option writes **ciphertext only** to a folder that the user already synchronizes with their chosen cloud provider. It is **not** a native Google Drive/OneDrive/S3 API integration and cannot verify cloud synchronization or cloud-server durability. The local `vault.key` is *never* included in these backup archives. Recovery on a replacement device requires separately preserving that key securely; a passphrase-wrapped recovery workflow is a future requirement. Previously exported plaintext `hosts.json` requires explicit `vault migrate`; the original remains until the owner verifies and removes it. The companion does not delete legacy data silently. The secure vault is device-local; the central SSH gateway remains optional.

## Android device deployment status

The CI Linux aarch64 artifact targets GNU/Linux, **not Android**. Do not install it as an Android APK or claim it is a ChatGPT Android custom plugin. Android requires an Android-targeted build, native packaging, and a verified supported ChatGPT connection/installation interface. Termux may be used as a separate, explicitly approved local test host, but does not provide ChatGPT Android with an automatic local MCP channel. No installation on a user's device has been performed.
