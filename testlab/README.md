# SSH Workspace — qvm test-lab manager

The initial `qvm` backend operates on dedicated **Linux libvirt/QEMU qcow2 test VMs**. It is separate from any existing Termux `qvm` command; do not overwrite that script without integrating its existing behavior.

## Command

```bash
qvm save-and-reset "a simulation of radius server"
```

The quoted string is mandatory and becomes the saved snapshot's **description**. The system captures both the local timestamp (including UTC offset) and the UTC timestamp automatically. An example archived disk name:

```text
linux-lab-20261121-084422-a-simulation-of-radius-server-8f2c4d61.qcow2
```

A matching JSON metadata file contains `description`, `saved_at_local`, `saved_at_utc`, `sha256`, and the original libvirt domain state. The command prints the saved date/time, description and archive path. Use `qvm snapshots` to inspect saved versions.

## Behavior

1. Validate the configured VM, disk layout and golden template.
2. Gracefully shut down a running VM; never force power-off and never copy a changing live disk.
3. Save the **current disk state** to a standalone qcow2 archive with SHA-256, timestamp, description and domain XML.
4. Verify the archive and create a new clean qcow2 overlay referencing the unchanged golden template.
5. Replace the disposable active disk, then restart if the VM was running.
6. Keep all archives; no automatic deletion.

**Limitation:** This backend saves disk and domain-XML state, **not RAM or in-flight process state**. It refuses multi-disk, UEFI NVRAM and TPM-backed guests. Windows 11 and macOS need drivers that capture those additional states. Only run against disposable, authorized lab VMs. The VM will shut down and boot cleanly; unsaved RAM is lost.

## Setup

Requires Linux, Python 3.10+, libvirt, `virsh`, `qemu-img`, filesystem permissions for the configured paths, and a previously created disposable VM/golden template.

```bash
sudo apt install python3 libvirt-clients qemu-utils
mkdir -p ~/.config/ssh-workspace-testlab
cp testlab/qvm.example.json ~/.config/ssh-workspace-testlab/qvm.json
python3 testlab/qvm.py --config ~/.config/ssh-workspace-testlab/qvm.json list
python3 testlab/qvm.py save-and-reset "a simulation of radius server" --dry-run
python3 testlab/qvm.py save-and-reset "a simulation of radius server"
python3 testlab/qvm.py snapshots
```

Adjust paths and the domain name before running. You can install a `qvm` launcher in your PATH pointing to this script, but check for existing commands first.

## Planned provider adapters

GitHub Actions already produces fresh hosted CI runners; cloud Windows images, macOS Apple-hardware VMs, Android Emulator snapshot/wipe-data and iOS Simulator erase/restore require separate drivers. This release does not imply those platforms can be reset with this backend.
