"""Enroll an SSH public key or certificate authority for a saved host."""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from server import SSHClientUnavailable, local_executable
from vault import Vault

CA_INSTALL = """umask 077
set -eu
cd "$HOME"
[ ! -L .ssh ] || exit 1
mkdir -p .ssh
chmod 700 .ssh
cd .ssh
[ ! -L authorized_keys ] && [ ! -L .ssh-workspace-enroll.lock ] || exit 1
exec 9>>.ssh-workspace-enroll.lock
flock -x 9
IFS= read -r entry
[ ! -L authorized_keys ] || exit 1
touch authorized_keys
chmod 600 authorized_keys
if ! grep -Fqx -- "$entry" authorized_keys; then
    printf '\\n%s\\n' "$entry" >> authorized_keys
fi
"""


def key_output(executable, flag, path):
    result = subprocess.run([executable, flag, str(path)], text=True, capture_output=True, check=True)
    return result.stdout


def public_key(path):
    text = path.read_text().strip()
    if len(text.splitlines()) != 1 or len(text) > 8000:
        raise ValueError("Use a single OpenSSH public key file")
    match = re.fullmatch(r"((?:ssh-|ecdsa-|sk-)[\w.@+-]+) ([A-Za-z0-9+/]+={0,2})(?:[ \t].*)?",
                         text.replace("\t", " "))
    if not match or "-cert-v01@" in match[1]:
        raise ValueError("Use a plain public key file. Use the certificate subcommand for a user certificate.")
    return " ".join(match.groups())


def ca_entry(ca_file, certificate, principal, keygen):
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]{0,127}", principal):
        raise ValueError("Supply one literal certificate principal")
    key = public_key(ca_file)
    fingerprint = key_output(keygen, "-lf", ca_file).split()[1]
    listing = key_output(keygen, "-Lf", certificate)
    if not re.search(r"(?m)^\s*Type: .* user certificate\s*$", listing):
        raise ValueError("Supply an OpenSSH user certificate")
    ca = re.search(r"(?m)^\s*Signing CA: \S+ (SHA256:\S+)", listing)
    if ca is None or ca[1] != fingerprint:
        raise ValueError("The certificate was signed by a different CA")
    principals = listing.partition("Principals:")[2].partition("Critical Options:")[0].split()
    if principal not in principals:
        raise ValueError("The certificate does not include that principal")
    return f'cert-authority,restrict,principals="{principal}" {key}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Saved SSH Workspace host alias")
    parser.add_argument("--bootstrap-key", type=Path,
                        help="Existing private key for this login, kept on the local machine")
    actions = parser.add_subparsers(dest="action", required=True)
    key = actions.add_parser("key")
    key.add_argument("public_key", type=Path)
    certificate = actions.add_parser("certificate")
    certificate.add_argument("--certificate", type=Path, required=True)
    certificate.add_argument("--ca-public-key", type=Path, required=True)
    certificate.add_argument("--principal", required=True)
    args = parser.parse_args()
    try:
        if not sys.stdin.isatty():
            raise ValueError("Run enrollment from an interactive local terminal")
        host = Vault.from_env().load().hosts.get(args.host)
        if host is None:
            raise ValueError("Choose a saved SSH Workspace host")
        bootstrap = []
        if args.bootstrap_key:
            bootstrap = ["-o", f"IdentityFile={args.bootstrap_key.resolve(strict=True)}"]
        options = [
            "-F", os.devnull, "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={host.known_hosts_file}",
            "-o", f"GlobalKnownHostsFile={os.devnull}", "-o", "UpdateHostKeys=no",
            "-o", "ClearAllForwardings=yes", "-o", "ForwardAgent=no",
            "-o", f"ConnectTimeout={host.connect_timeout}", "-p", str(host.port), *bootstrap,
        ]
        keygen = shutil.which("ssh-keygen")
        if keygen is None:
            raise ValueError("Install ssh-keygen from your native OpenSSH package")
        if args.action == "key":
            copy_id = shutil.which("ssh-copy-id")
            if copy_id is None:
                raise ValueError("Install ssh-copy-id from your native OpenSSH package")
            public_key(args.public_key)
            key_output(keygen, "-lf", args.public_key.resolve(strict=True))
            return subprocess.run([
                copy_id, *options, "-i", str(args.public_key.resolve(strict=True)),
                f"{host.account}@{host.address}",
            ]).returncode
        entry = ca_entry(args.ca_public_key, args.certificate, args.principal, keygen)
        return subprocess.run(
            [local_executable("ssh"), "-T", *options, "-l", host.account, "--", host.address, CA_INSTALL],
            input=entry + "\n", text=True,
        ).returncode
    except (OSError, ValueError, SSHClientUnavailable, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    sys.exit(main())
