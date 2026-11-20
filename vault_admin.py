"""Manage SSH Workspace profiles without putting passwords in command arguments."""

import argparse
import getpass
import json
import os
import warnings
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import ValidationError

from vault import Host, Inventory, Vault, VaultError

ALGORITHMS = ("ciphers", "kex_algorithms", "macs", "host_key_algorithms", "pubkey_algorithms")


def prompt_password():
    if not os.isatty(0):
        raise VaultError("Use an interactive terminal to enter the SSH password")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            value = getpass.getpass("SSH password: ")
            repeat = getpass.getpass("Repeat SSH password: ")
        except getpass.GetPassWarning:
            raise VaultError("Password entry requires a terminal with echo disabled") from None
    if value != repeat:
        raise VaultError("Passwords do not match")
    return value


def put_profile(inventory, args, password):
    existing = inventory.hosts.get(args.alias)
    profile = existing.model_dump(mode="python") if existing else {}
    for field in ("address", "hostname", "port", "account", "group", "comment", "auth",
                  "identity_file", "certificate_file", "known_hosts_file", "connect_timeout",
                  "protocol_compression", "bind_address", "bind_interface"):
        value = getattr(args, field)
        if value is not None:
            profile[field] = value
    for field in ("bind_address", "bind_interface"):
        if getattr(args, field) == "":
            profile[field] = None
        elif getattr(args, field) is not None:
            alternate = "bind_interface" if field == "bind_address" else "bind_address"
            if getattr(args, alternate) is None:
                profile[alternate] = None
    for field in ALGORITHMS:
        value = getattr(args, field)
        if value is not None:
            profile[field] = value.split(",") if value else None
    if args.clear_certificate:
        profile["certificate_file"] = None
    if password is not None:
        profile.update(auth="password", password=password, identity_file=None,
                       certificate_file=None, pubkey_algorithms=None)
    elif args.auth == "publickey":
        profile["password"] = None
    inventory.hosts[args.alias] = Host.model_validate(profile)
    return inventory


def read_profiles(vault, args):
    hosts = vault.load().hosts
    aliases = [args.alias] if args.action == "show" else sorted(hosts)
    output = []
    for alias in aliases:
        if alias not in hosts:
            raise VaultError("Unknown host alias")
        profile = hosts[alias]
        if args.action == "list" and args.group is not None and profile.group != args.group:
            continue
        output.append({"alias": alias, **profile.model_dump(mode="json", exclude={"password"})})
    return output[0] if args.action == "show" else output


def remove_profile(inventory, alias):
    if inventory.hosts.pop(alias, None) is None:
        raise VaultError("Unknown host alias")
    return inventory


def legacy_inventory(path):
    source = json.loads(path.read_bytes())
    if not isinstance(source, dict) or "hosts" not in source or not set(source) <= {"hosts", "grants"}:
        raise VaultError("Choose an SSH Workspace 0.1.0 inventory JSON file")
    inventory = Inventory.model_validate({"hosts": source["hosts"]})
    if any(host.password is not None for host in inventory.hosts.values()):
        raise VaultError("Import legacy key profiles first, then set passwords interactively")
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    keygen = commands.add_parser("keygen")
    keygen.add_argument("key_file", type=Path)
    commands.add_parser("init")
    migrate = commands.add_parser("import-json")
    migrate.add_argument("source", type=Path)
    put = commands.add_parser("put")
    put.add_argument("alias")
    for field in ("address", "hostname", "account", "group", "comment", "bind_address", "bind_interface", *ALGORITHMS):
        put.add_argument("--" + field.replace("_", "-"))
    for field in ("port", "connect-timeout"):
        put.add_argument("--" + field, type=int)
    for field in ("identity-file", "certificate-file", "known-hosts-file"):
        put.add_argument("--" + field, type=Path)
    put.add_argument("--auth", choices=("publickey", "password"))
    put.add_argument("--set-password", action="store_true")
    put.add_argument("--clear-certificate", action="store_true")
    put.add_argument("--compression", dest="protocol_compression", action=argparse.BooleanOptionalAction)
    listing = commands.add_parser("list")
    listing.add_argument("--group")
    for action in ("show", "remove"):
        commands.add_parser(action).add_argument("alias")
    args = parser.parse_args()
    try:
        if args.action == "keygen":
            with os.fdopen(os.open(args.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as key:
                key.write(Fernet.generate_key() + b"\n")
            return
        vault = Vault.from_env()
        if args.action == "init":
            vault.update(lambda inventory: inventory, initialize=True)
        elif args.action == "import-json":
            vault.update(lambda _: legacy_inventory(args.source), initialize=True)
        elif args.action == "put":
            if args.set_password and (
                args.auth == "publickey" or args.identity_file or args.certificate_file or args.pubkey_algorithms
            ):
                raise VaultError("Do not combine password entry with public-key options")
            password = prompt_password() if args.set_password else None
            vault.update(lambda inventory: put_profile(inventory, args, password))
        elif args.action in {"list", "show"}:
            print(json.dumps(read_profiles(vault, args), indent=2))
        else:
            vault.update(lambda inventory: remove_profile(inventory, args.alias))
    except (ValidationError, KeyError, ValueError, OSError, EOFError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
