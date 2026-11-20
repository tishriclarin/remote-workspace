"""Select and refresh a cache of locally installed native OpenSSH clients."""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from activity import log_activity, read_history
from local_paths import config_directory

TRACKS = ("development", "stable", "old-stable")
DEFAULTS = ("latest", "system")
VERSION = re.compile(r"\bOpenSSH_(\d+)\.(\d+)(?:p(\d+))?(?=[^0-9]|$)")
PROFILE_FIELDS = frozenset({"connect_timeout", "protocol_compression", "bind_address", "bind_interface"})


def read_state():
    try:
        return (config_directory() / "ssh-clients.json").read_text()
    except FileNotFoundError:
        return '{"registered":[],"cache":[],"selection":"latest"}'


def change_state(update):
    folder = config_directory()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / "ssh-clients.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(read_state())
        update(state)
        fd, temporary = tempfile.mkstemp(dir=folder)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(state, output, indent=2)
                output.write("\n")
            os.replace(temporary, folder / "ssh-clients.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
    return state


def inspect_client(path, track):
    result = subprocess.run(
        [path, "-V"], stdin=subprocess.DEVNULL, capture_output=True, timeout=5, check=True,
    )
    match = VERSION.search((result.stderr + result.stdout).decode(errors="replace"))
    if match is None:
        raise ValueError("The selected executable did not identify itself as OpenSSH")
    return {
        "id": f"{track}:{path}", "path": path, "track": track,
        "version": match[0], "order": [int(part or 0) for part in match.groups()],
    }


def refresh(state):
    registered = list(state["registered"])
    system = shutil.which("ssh")
    if system:
        registered.append({"path": str(Path(system).resolve()), "track": "stable"})
    clients = {}
    for entry in registered:
        try:
            client = inspect_client(entry["path"], entry["track"])
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        clients[client["id"]] = client
    retained = []
    for track in TRACKS:
        by_major = {}
        for client in sorted(clients.values(), key=lambda item: item["order"], reverse=True):
            if client["track"] == track:
                by_major.setdefault(client["order"][0], client)
        retained.extend(list(by_major.values())[:4])
    state["cache"] = retained


def register(path, track):
    native = str(Path(path).expanduser().resolve(strict=True))
    inspect_client(native, track)

    def update(state):
        record = {"path": native, "track": track}
        if record not in state["registered"]:
            state["registered"].append(record)
        refresh(state)

    return change_state(update)


def select(choice):
    def update(state):
        if choice not in DEFAULTS and not any(item["id"] == choice for item in state["cache"]):
            raise ValueError("Choose latest, system, or an ID from the current client cache")
        state["selection"] = choice

    return change_state(update)


def validate_profile_defaults(values):
    from vault import ConnectionOptions

    if not isinstance(values, dict) or not values.keys() <= PROFILE_FIELDS:
        raise ValueError("Use a JSON object with only connect_timeout, protocol_compression, bind_address, or bind_interface.")
    return ConnectionOptions.model_validate(values, strict=True).model_dump(mode="json", exclude_unset=True)


def profile_defaults():
    return validate_profile_defaults(json.loads(read_state()).get("profile_defaults", {}))


def save_profile_defaults(raw):
    values = validate_profile_defaults(json.loads(raw))
    return change_state(lambda state: state.update(profile_defaults=values))


def fetch_native():
    try:
        state = download_native()
    except (OSError, ValueError, subprocess.SubprocessError):
        log_activity("fetch_native_client", "failed")
        raise
    log_activity("fetch_native_client", "completed")
    return state


def download_native():
    tools = [shutil.which(name) for name in ("apt-get", "dpkg", "dpkg-deb")]
    if not all(tools):
        raise ValueError("Native downloads use Debian or Ubuntu APT. Register a native client from your own package manager.")
    apt, dpkg, deb = tools
    machine = subprocess.check_output([dpkg, "--print-architecture"], text=True).strip()
    managed = config_directory() / "native-clients"
    managed.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=managed) as staging:
        subprocess.run([
            apt, "-o", "APT::Get::AllowUnauthenticated=false",
            "-o", "Acquire::AllowInsecureRepositories=false", "download",
            f"openssh-client:{machine}",
        ], cwd=staging, capture_output=True, text=True, check=True, timeout=180)
        packages = list(Path(staging).glob("*.deb"))
        if len(packages) != 1:
            raise ValueError("APT did not return one native OpenSSH client package")
        package = packages[0]

        def field(name):
            return subprocess.check_output([deb, "-f", package, name], text=True).strip()

        if (field("Package"), field("Architecture")) != ("openssh-client", machine):
            raise ValueError("The downloaded OpenSSH package does not match this machine")
        version = field("Version")
        if not re.fullmatch(r"[A-Za-z0-9.+:~_-]+", version):
            raise ValueError("APT returned an unexpected package version")
        unpacked = Path(staging) / "package"
        subprocess.run([deb, "-x", package, unpacked], check=True, capture_output=True)
        relative = Path("usr/bin/ssh")
        inspect_client(str(unpacked / relative), "stable")
        destination = managed / machine / "ssh"

        def update(state):
            destination.parent.mkdir(exist_ok=True, mode=0o700)
            os.replace(unpacked / relative, destination)
            native = str(destination.resolve())
            previous = [item for item in state["registered"] if item.get("managed")]
            state["registered"] = [item for item in state["registered"] if not item.get("managed")]
            state["registered"].insert(0, {"path": native, "track": "stable", "managed": True})
            if any(state["selection"] == f'stable:{item["path"]}' for item in previous):
                state["selection"] = f"stable:{native}"
            refresh(state)

        state = change_state(update)
    return state


def selected_executable():
    state = json.loads(read_state())
    system = shutil.which("ssh")
    choice = state["selection"]
    available = [entry for entry in state["cache"] if os.access(entry["path"], os.X_OK)]
    if choice == "system":
        if system:
            validate_system_client(system)
        return system
    if choice == "latest":
        stable = [entry for entry in available if entry["track"] == "stable"]
        if system:
            try:
                stable.append(validate_system_client(system))
            except ValueError:
                if not stable:
                    raise
        latest = max(stable, key=lambda entry: entry["order"], default=None)
        return latest["path"] if latest else None
    for entry in available:
        if choice == entry["id"]:
            return entry["path"]
    raise ValueError("The selected OpenSSH client is unavailable. Refresh the cache and select a client.")


def validate_system_client(path):
    try:
        return inspect_client(path, "stable")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ValueError("The system SSH executable could not be verified as OpenSSH.") from error


def refresh_cache():
    try:
        state = change_state(refresh)
    except (OSError, ValueError, subprocess.SubprocessError):
        log_activity("refresh_client_cache", "failed")
        raise
    log_activity("refresh_client_cache", "completed")
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("ui")
    commands.add_parser("refresh")
    commands.add_parser("list")
    commands.add_parser("fetch-native")
    history = commands.add_parser("history")
    history.add_argument("--lines", type=int, default=50)
    defaults = commands.add_parser("defaults")
    defaults.add_argument("json", nargs="?")
    addition = commands.add_parser("register")
    addition.add_argument("path")
    addition.add_argument("--track", choices=TRACKS, required=True)
    selection = commands.add_parser("select")
    selection.add_argument("id")
    args = parser.parse_args()
    try:
        if args.action == "ui":
            from settings_ui import show_ui

            show_ui()
            return
        if args.action == "history":
            print(read_history(args.lines))
            return
        if args.action == "defaults":
            values = (save_profile_defaults(args.json)["profile_defaults"]
                      if args.json is not None else profile_defaults())
            print(json.dumps(values, indent=2))
            return
        if args.action == "refresh":
            state = refresh_cache()
        elif args.action == "fetch-native":
            state = fetch_native()
        elif args.action == "register":
            state = register(args.path, args.track)
        elif args.action == "select":
            state = select(args.id)
        else:
            state = json.loads(read_state())
        print(json.dumps({"selection": state["selection"], "cache": state["cache"]}, indent=2))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
