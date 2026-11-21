# Portable vault recovery — SSH Workspace v0.7.0

SSH Workspace stores device host profiles in an authenticated **XChaCha20-Poly1305** encrypted vault. The symmetric vault key remains in a local owner-only file named `vault.key`; the ordinary encrypted backups never contain that key.

A replacement device cannot read those backup files without the original vault key. To support recovery, the companion can now create a **separate passphrase-protected recovery key envelope**, encrypted with XChaCha20-Poly1305 using an **Argon2id-derived** encryption key. KDF parameters are 64 MiB memory, three iterations and one lane, plus a random 16-byte salt and a random 24-byte nonce. The recovery key file does not contain host inventory.

## Prepare on the original device

1. Configure a local backup folder or a pre-existing cloud-synced folder. This is a ciphertext export; SSH Workspace does **not** install or authenticate a cloud provider:

       sshworkspace backup configure local ~/sshworkspace-backups
       sshworkspace backup configure cloud-sync ~/my-cloud-sync/sshworkspace-backups

2. Back up the encrypted device inventory with a human-readable description:

       sshworkspace backup run "before replacing my laptop"

   The resulting `.vault` file may be synchronized to your provider. The local `vault.key` will not be included.

3. On an interactive trusted terminal, export a separate offline recovery key envelope:

       sshworkspace vault recovery-export /secure/offline/location/sshworkspace.sshwskey

   Enter and confirm a **unique high-entropy recovery passphrase with at least 16 characters**. The terminal hides the input. SSH Workspace does not send it to ChatGPT or a model API.

4. Store the `.sshwskey` file **separately** from the synced `.vault` archive; safeguard the passphrase separately as well. A stolen envelope and ciphertext backup can be attacked offline, so use a strong and unique passphrase. Without both the encrypted backup and a way to recover the key, new-device restoration is impossible.

## Restore to a replacement device

The target configuration **must not contain** a `vault.key`, `hosts.vault`, or legacy `hosts.json`. This protects existing profiles and avoids overwrite. Use a fresh configuration directory (or new OS user) rather than deleting existing data:

    export SSHWORKSPACE_HOME="$HOME/.config/ssh-workspace-recovered"
    sshworkspace vault recovery-import /secure/offline/location/sshworkspace.sshwskey /cloud-sync/backup-file.vault --confirm
    sshworkspace vault status
    sshworkspace status

The import prompts for the recovery passphrase. It checks envelope authentication, decrypts the backup, validates the host inventory shape and **only then** writes the recovered key and encrypted vault to the new directory. A bad passphrase, changed ciphertext, or existing vault causes the operation to fail. Do not run `sshworkspace setup` on the target directory before import; setup creates a distinct key.

**Important:** The vault contains SSH key/certificate **references**; it does not transfer private SSH keys, agent keys or OS keystore secrets. Reinstall and authorize those separately on a new device, and verify each SSH host key independently. Recovered inventory alone does not grant SSH access.

## Security and platform limitations

- The local vault key is protected by filesystem permissions on supported Unix systems. Native OS keystore wrapping is a future hardening item.
- Recovery uses a **portable key envelope**, not the user's ChatGPT session credentials.
- An owner-approved fresh restore is necessary. It is not automatically triggered by ChatGPT tool calls.
- The recovery file is versioned (`SSHWSRCV1`) and contains **only** an encrypted vault key; the vault data remains in its own `.vault` file.
- File system rollback across simultaneous power failure is not transactional across the key and vault files; perform restoration on a fresh directory and retain both original recovery artifacts.
- The backup provider mode `cloud-sync` currently writes encrypted archives to a user-chosen local folder only. It does not guarantee delivery to a remote cloud provider.
