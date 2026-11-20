# SSH Workspace

SSH Workspace is a local plugin for ChatGPT and Codex. Its MCP server runs over standard input and output on the machine running the local plugin. The same machine opens the SSH TCP connections, using its own network routes and source interfaces. A plugin installed on a desktop does not use a Samsung phone's loopback or VPN. To reach Termux from that desktop, save the phone address that the desktop can reach.

## Local setup

On Linux, use Python 3.12 or later and your distribution's supported OpenSSH client. The plugin finds `ssh` on its local `PATH`. Password profiles also require `sshpass` on that path. The same source package works with native Python dependencies on each architecture. If you already have Python and OpenSSH, reuse them. On Debian 13, install any missing packages as needed.

```bash
sudo apt install python3 python3-venv openssh-client sshpass
workspace_dir="${XDG_CONFIG_HOME:-$HOME/.config}/ssh-workspace"
install -d -m 700 "$workspace_dir"
python3 -m venv "$workspace_dir/venv"
"$workspace_dir/venv/bin/python" -m pip install -r requirements.txt
"$workspace_dir/venv/bin/python" vault_admin.py keygen "$workspace_dir/vault.key"
"$workspace_dir/venv/bin/python" vault_admin.py init
```

Run these commands from the unpacked plugin directory. The plugin manifest starts `launch.py`, which uses the workspace virtual environment or its packaged Python dependencies. Start a local thread after installing the plugin. For a fresh client without the plugin loader, the command `python3 /absolute/path/to/launch.py` also provides the local stdio MCP server.

The vault and its key default to `hosts.vault` and `vault.key` in the workspace configuration directory. The vault uses authenticated encryption for all profile fields, including passwords. Keep the key separate from any vault backup. Environment variables `SSH_WORKSPACE_VAULT` and `SSH_WORKSPACE_VAULT_KEY_FILE` override those paths when set in the process launching the plugin. Restrict both files to your OS user. The app reloads the vault per tool call.

When migrating the v0.1 JSON inventory, run `vault_admin.py import-json /path/to/old-inventory.json` in place of `init`. It imports the host profiles into a new encrypted vault. The local OS user owns the vault and the former remote OAuth grants do not apply. Protect the legacy plaintext copy according to your backup policy.

## Manage profiles

Use the workspace Python from setup for the following examples. Each profile has a saved alias, optional display hostname, SSH address or IP, port, group, comment, username, and authentication method. Verify the remote host key independently and store it in a dedicated known_hosts file. Use `[host]:port` for nonstandard ports.

```bash
python vault_admin.py put branch-linux \
  --hostname debian-branch --address 192.0.2.10 --port 22 \
  --group Field --comment 'Debian branch host' --account diagnostics \
  --identity-file /absolute/path/to/branch-key \
  --certificate-file /absolute/path/to/branch-key-cert.pub \
  --known-hosts-file /absolute/path/to/branch-known-hosts

python vault_admin.py put termux \
  --address 192.0.2.20 --port 8022 --group Lab --account TERMUX_USERNAME \
  --known-hosts-file /absolute/path/to/termux-known-hosts --set-password

python vault_admin.py show branch-linux
python vault_admin.py list --group Field
python vault_admin.py put branch-linux --comment 'Updated branch host comment'
python vault_admin.py remove termux
```

Password entry uses a masked terminal prompt. The plugin passes the decoded password to OpenSSH via `sshpass` and an anonymous pipe. The admin list and show commands omit passwords, and MCP only returns aliases and diagnostic results. OpenSSH user certificates use an accompanying private key. The vault encrypts the key and certificate paths. Manage the external files under your OS account. Key-based authentication is unattended and expects a usable private key with no interactive passphrase prompt.

On Debian or Ubuntu targets, you can restrict a dedicated key to the included `ssh-diagnostics.sh` using an OpenSSH `restrict,command="…"` authorized_keys entry. On hosts using password authentication, place the diagnostics account under an appropriate server-side `ForceCommand` policy if you want the account itself restricted to the same probes. Kernel and CPU checks use `uname`. Uptime reads `/proc/uptime`.

## Override connection settings

Save persistent defaults with `vault_admin.py put ALIAS`. Supported connection settings are ciphers, key exchange algorithms, MACs, server host-key algorithms, user public-key algorithms, compression, connection timeout, and one local source IP or local interface. For example:

```bash
python vault_admin.py put branch-linux --bind-interface enp3s0 \
  --ciphers aes256-ctr,chacha20-poly1305@openssh.com \
  --kex-algorithms curve25519-sha256 --connect-timeout 6
```

In chat, ask to apply a setting for a single check, for example “Check SSH to branch-linux once using local source IP 192.0.2.5 and cipher aes256-ctr.” Use an address actually assigned to the local machine. Single-check options leave the profile intact. To change the destination, port, account, or credentials, edit the saved profile locally. Strict host-key verification applies to every connection.

OpenSSH negotiates using its own defaults unless you supply an override. The installed client must support any selected option and algorithm. For example, `ssh -Q cipher`, `ssh -Q kex`, and `ssh -Q mac` list what the client knows. An explicit override can still fail if the remote host does not offer a matching algorithm.

## Verify and package

Run `python3 -m unittest discover -s tests -v` from the source directory. Build the portable source ZIP with `python3 package_plugin.py --output ssh-workspace-0.2.1.zip`. For an offline build, install the Python dependencies into a staging directory with `pip install --target /path/to/staging -r requirements.txt` for the intended Linux architecture and Python version. Build with `--vendor /path/to/staging --publisher 'Verified Publisher Name'`. Both packaging modes use the installed OpenSSH client. OpenSSH and sshpass are outside the package.

Public directory submission for this execution model is [desktop-only](https://developers.openai.com/plugins/deploy/desktop-only). OpenAI requires the submitting organization to be approved for local MCP submissions.
