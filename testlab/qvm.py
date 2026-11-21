#!/usr/bin/env python3
"""Archive a libvirt test VM's disk state, then restore its pristine qcow2 template.

This initial backend supports a single qcow2 disk without persistent NVRAM/TPM.
It deliberately does not save guest RAM. Never use against production guests.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

CONFIG = Path.home() / ".config/ssh-workspace-testlab/qvm.json"


class QVMError(Exception):
    pass


def command(*argv: str, timeout: int = 120) -> str:
    try:
        result = subprocess.run(
            list(argv), check=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise QVMError(f"{argv[0]} failed: {error}") from None


def read_config(path: Path) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise QVMError(f"Cannot read configuration {path}: {error}") from None
    if not isinstance(config, dict) or not isinstance(config.get("machines"), dict):
        raise QVMError("Configuration must contain a machines object")
    return config


def get_machine(config: dict, name: str | None) -> tuple[str, dict]:
    machines = config["machines"]
    selected = name or config.get("default_vm")
    if selected is None and len(machines) == 1:
        selected = next(iter(machines))
    if not isinstance(selected, str) or selected not in machines:
        raise QVMError("Select a known VM with --vm or set default_vm")
    vm = machines[selected]
    if not isinstance(vm, dict) or vm.get("backend") != "libvirt-qcow2":
        raise QVMError("Only libvirt-qcow2 backend is implemented")
    for key in ("domain", "disk", "template", "archives"):
        if not isinstance(vm.get(key), str) or not vm[key].strip():
            raise QVMError(f"Machine {selected}: missing {key}")
    return selected, vm


def snapshot_name(description: str, at: datetime | None = None) -> tuple[str, str, str]:
    if not isinstance(description, str) or not description.strip() or len(description) > 200:
        raise QVMError("Description must be between 1 and 200 characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in description):
        raise QVMError("Description cannot contain control characters")
    at = (at or datetime.now(timezone.utc)).astimezone()
    local_time = at.isoformat(timespec="seconds")
    utc_time = at.astimezone(timezone.utc).isoformat(timespec="seconds")
    slug = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")[:55] or "snapshot"
    stamp = at.strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slug}-{uuid.uuid4().hex[:8]}", local_time, utc_time


def paths(vm: dict) -> tuple[Path, Path, Path]:
    disk = Path(vm["disk"]).expanduser().absolute()
    template = Path(vm["template"]).expanduser().absolute()
    archives = Path(vm["archives"]).expanduser().absolute()
    if disk == template or disk.is_symlink() or template.is_symlink():
        raise QVMError("Template and disk must be distinct, non-symlinked files")
    if archives == disk.parent or archives == template.parent:
        raise QVMError("Archive directory cannot be the active disk or template directory")
    if archives == disk or archives == template:
        raise QVMError("Archive path overlaps a disk")
    if disk.suffix != ".qcow2" or template.suffix != ".qcow2":
        raise QVMError("Only qcow2 images are supported")
    if not disk.is_file() or not template.is_file():
        raise QVMError("Configured disk or golden template does not exist")
    return disk, template, archives


def validate_domain(domain: str, disk: Path) -> str:
    xml = command("virsh", "dumpxml", "--inactive", domain, timeout=30)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise QVMError("Invalid libvirt domain XML") from None
    devices = root.findall("./devices/disk[@device='disk']")
    if len(devices) != 1:
        raise QVMError("Reset requires exactly one disk; multiple disks need a full-state driver")
    source = devices[0].find("source")
    if source is None or source.get("file") is None:
        raise QVMError("Only local file-backed libvirt disks are supported")
    if Path(source.get("file")).expanduser().absolute() != disk:
        raise QVMError("Configured disk differs from the domain's attached disk")
    if root.find("./os/nvram") is not None or root.find("./devices/tpm") is not None:
        raise QVMError("VM has NVRAM or TPM state; refusing incomplete backup/reset")
    return xml


def vm_state(domain: str) -> str:
    return command("virsh", "domstate", domain, timeout=30).lower()


def shut_down(domain: str) -> bool:
    state = vm_state(domain)
    if state == "shut off":
        return False
    if state != "running":
        raise QVMError(f"VM is in unsupported state: {state}")
    command("virsh", "shutdown", domain, timeout=30)
    until = time.monotonic() + 120
    while time.monotonic() < until:
        if vm_state(domain) == "shut off":
            return True
        time.sleep(2)
    raise QVMError("Graceful shutdown timed out. VM disk was not modified.")


def disk_info(disk: Path) -> dict:
    try:
        info = json.loads(command("qemu-img", "info", "--output=json", "-f", "qcow2", str(disk)))
    except ValueError:
        raise QVMError("qemu-img returned invalid disk details") from None
    if info.get("format") != "qcow2" or not isinstance(info.get("virtual-size"), int):
        raise QVMError("Disk image is not valid qcow2")
    return info


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_metadata(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def save_and_reset(name: str, vm: dict, description: str,
                   dry_run: bool = False, restart: bool = True) -> dict:
    disk, template, archives = paths(vm)
    domain = vm["domain"]
    xml = validate_domain(domain, disk)
    state = vm_state(domain)
    if state not in ("running", "shut off"):
        raise QVMError(f"VM must be running or shut off, currently: {state}")
    label, saved_at, saved_utc = snapshot_name(description)
    if dry_run:
        return {
            "vm": name, "description": description, "saved_at_local": saved_at,
            "would_archive": str(archives / f"{name}-{label}.qcow2"),
            "would_restore": str(template), "state": state, "dry_run": True
        }
    archives.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(archives, 0o700)
    with (archives / ".qvm.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        was_running = shut_down(domain)
        if disk_info(disk)["virtual-size"] != disk_info(template)["virtual-size"]:
            raise QVMError("Golden template and current disk have different virtual sizes")
        archive = archives / f"{name}-{label}.qcow2"
        temporary_archive = archives / f".{name}-{label}.pending.qcow2"
        next_disk = disk.with_name(f".{disk.name}-{label}.next")
        if any(path.exists() for path in (archive, temporary_archive, next_disk)):
            raise QVMError("Snapshot or temporary file already exists")
        switched = False
        try:
            # Flatten the current qcow2 image so the archive is self-contained.
            command("qemu-img", "convert", "-f", "qcow2", "-O", "qcow2",
                    str(disk), str(temporary_archive), timeout=3600)
            command("qemu-img", "check", "-f", "qcow2", str(temporary_archive), timeout=300)
            digest = hash_file(temporary_archive)
            os.chmod(temporary_archive, 0o600)
            os.replace(temporary_archive, archive)
            record = {
                "id": label, "vm": name, "description": description,
                "saved_at_local": saved_at, "saved_at_utc": saved_utc,
                "saved_disk": archive.name, "sha256": digest,
                "domain": domain, "original_state": state,
                "ram_state_saved": False,
                "domain_xml": f"{name}-{label}.xml"
            }
            write_metadata(archives / record["domain_xml"], xml)
            write_metadata(archives / f"{name}-{label}.json", json.dumps(record, indent=2) + "\n")
            command("qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
                    "-b", str(template), str(next_disk), timeout=60)
            command("qemu-img", "check", "-f", "qcow2", str(next_disk), timeout=60)
            os.chmod(next_disk, 0o600)
            # The old disk is only replaced after the archive is validated and recorded.
            os.replace(next_disk, disk)
            switched = True
        finally:
            temporary_archive.unlink(missing_ok=True)
            if not switched:
                next_disk.unlink(missing_ok=True)
        restarted = False
        if was_running and restart:
            command("virsh", "start", domain, timeout=60)
            restarted = True
        return {
            "vm": name, "snapshot_id": label, "description": description,
            "saved_at_local": saved_at, "saved_at_utc": saved_utc,
            "saved_disk": str(archive), "sha256": digest,
            "reset_to": str(template), "restarted": restarted,
            "ram_state_saved": False
        }


def snapshot_list(name: str, vm: dict) -> list[dict]:
    archives = Path(vm["archives"]).expanduser()
    items = []
    if archives.exists():
        for path in sorted(archives.glob(f"{name}-*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("vm") == name and "saved_disk" in data:
                    items.append(data)
            except (OSError, ValueError):
                continue
    return items


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qvm", description="SSH Workspace test VM manager")
    parser.add_argument("--config", type=Path, default=CONFIG)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    status = actions.add_parser("status")
    status.add_argument("--vm")
    snapshots = actions.add_parser("snapshots")
    snapshots.add_argument("--vm")
    reset = actions.add_parser("save-and-reset",
                               help="Archive current disk with timestamp and description, then restore template")
    reset.add_argument("description", help="Quoted description of the saved state")
    reset.add_argument("--vm")
    reset.add_argument("--dry-run", action="store_true")
    reset.add_argument("--no-restart", action="store_true")
    args = parser.parse_args(argv)
    config = read_config(args.config)
    if args.action == "list":
        result = {"default_vm": config.get("default_vm"), "machines": list(config["machines"])}
    else:
        name, vm = get_machine(config, args.vm)
        if args.action == "status":
            result = {"vm": name, "state": vm_state(vm["domain"])}
        elif args.action == "snapshots":
            result = {"vm": name, "snapshots": snapshot_list(name, vm)}
        else:
            result = save_and_reset(name, vm, args.description,
                                    dry_run=args.dry_run, restart=not args.no_restart)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(cli())
    except (QVMError, OSError, ValueError) as exc:
        print(f"qvm: {exc}", file=sys.stderr)
        sys.exit(1)
