# SSH Workspace release review

## Listing

| Field | Value |
| --- | --- |
| Display name | SSH Workspace |
| Category | Developer Tools |
| Subtitle | Local SSH host diagnostics |
| Publisher | Use the verified developer or business name in the submission portal |
| Logo and composer icon | `assets/logo.webp` serves both slots |

The manifest contains the listing copy and three starter prompts. OpenAI's published desktop-only instructions and image validation rules specify the square listing and composer assets. The documented flow does not list a mandatory banner or screenshot. Capture actual screenshots after validating the installed desktop experience if the portal asks for them.

## Data handling draft

SSH Workspace stores connection profiles, host comments, and saved passwords in an encrypted vault on the machine running the plugin. The vault key is kept in a separate local file. File permissions protect both files from other OS users. A process with access to both files can decrypt the vault. SSH private keys and user certificates remain in user-managed files.

The local SSH client connects directly to saved hosts for the requested check. The plugin sends saved aliases and the requested diagnostic results to the host conversation. The application that hosts the conversation handles that information under its own settings and policies. Plugin diagnostics omit passwords, private keys, and raw terminal output. The plugin uses OS logging for local activity history and omits credentials, host identifiers, and raw SSH output. There is no plugin-operated telemetry service.

Profiles persist locally until the operator removes them. Removing a profile does not erase prior conversation results or revoke remote credentials. Manage saved profiles through `vault_admin.py`. Native client downloads are an explicit local action and use the machine's configured APT repositories.

## Before directory submission

- Confirm OpenAI approval for local MCP submissions under the verified publishing identity. Obtain submission access and complete the portal attestations.
- Build each advertised target with its Python dependencies, preserve third-party licenses, and scan exact dependency versions for advisories. Record the package SHA-256 and build provenance.
- Test installation, upgrade, and uninstall from a clean ChatGPT desktop installation on Linux x86-64 and ARM64 before making either platform claim. Confirm that uninstall and upgrade preserve the vault and its key as documented.
- Exercise a live signed APT download, selection and refresh, password login using a test credential, failed authentication, and timeout cleanup. Existing automated tests and the loopback certificate check do not substitute for these installation and integration checks.
- Smoke-test alias listing and group filtering, connectivity, platform, uptime, and a one-time source binding. Confirm unknown aliases, changed host keys, unsupported clients, and attempts to override the destination or request arbitrary commands fail safely.
- Review credential storage and complete a full dependency and application security review before calling the build production-ready. Enrollment and client downloads stay in local user-operated tools. Consider optional OS keyring storage in a later release.

[Desktop-only submission](https://developers.openai.com/plugins/deploy/desktop-only) · [Listing and image rules](https://developers.openai.com/plugins/deploy/submission-errors) · [Security and privacy](https://developers.openai.com/plugins/guides/security-privacy)
