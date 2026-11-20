"""Select and refresh a cache of locally installed native OpenSSH clients."""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from local_paths import config_directory

TRACKS = ("development", "stable", "old-stable")
DEFAULTS = ("latest", "system")
VERSION = re.compile(r"\bOpenSSH_(\d+)\.(\d+)(?:p(\d+))?(?=[^0-9]|$)")


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


def fetch_native():
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
        return system
    if choice == "latest":
        stable = [entry for entry in available if entry["track"] == "stable"]
        if system:
            try:
                stable.append(inspect_client(system, "stable"))
            except (OSError, ValueError, subprocess.SubprocessError):
                if not stable:
                    return system
        latest = max(stable, key=lambda entry: entry["order"], default=None)
        return latest["path"] if latest else None
    for entry in available:
        if choice == entry["id"]:
            return entry["path"]
    raise ValueError("The selected OpenSSH client is unavailable. Refresh the cache and select a client.")


def show_ui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("SSH Workspace Clients")
    panel = ttk.Frame(root, padding=16)
    panel.pack(fill="both", expand=True)
    choice = tk.StringVar()
    track = tk.StringVar(value="stable")
    status = tk.StringVar()
    labels = {}
    executor = ThreadPoolExecutor(max_workers=1)
    ttk.Label(panel, text="OpenSSH client").pack(anchor="w")
    menu = ttk.Combobox(panel, textvariable=choice, state="readonly", width=56)
    menu.pack(fill="x", pady=(4, 8))

    def render(state):
        labels.clear()
        labels.update({"Latest available stable": "latest", "System client on PATH": "system"})
        for client in state["cache"]:
            labels[f'{client["version"]} · {client["track"]} · {client["path"]}'] = client["id"]
        menu.configure(values=list(labels))
        choice.set(next((label for label, value in labels.items()
                         if value == state["selection"]), ""))
        status.set(f'{len(state["cache"])} native clients in cache')

    def run(action):
        try:
            render(action())
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            messagebox.showerror("SSH Workspace", str(error), parent=root)

    def add_client():
        path = filedialog.askopenfilename(title="Select an installed OpenSSH executable", parent=root)
        if path:
            run(lambda: register(path, track.get()))

    def download():
        download_button.configure(state="disabled")
        status.set("Fetching the native client from APT…")
        job = executor.submit(fetch_native)

        def finish():
            if not job.done():
                root.after(100, finish)
                return
            run(job.result)
            download_button.configure(state="normal")

        root.after(100, finish)

    menu.bind("<<ComboboxSelected>>", lambda _: run(lambda: select(labels[choice.get()])))
    ttk.Button(panel, text="Refresh client cache", command=lambda: run(lambda: change_state(refresh))).pack(anchor="w")
    buttons = ttk.Frame(panel)
    buttons.pack(anchor="w", pady=8)
    ttk.Combobox(buttons, textvariable=track, state="readonly", values=TRACKS, width=14).pack(side="left")
    ttk.Button(buttons, text="Add native client", command=add_client).pack(side="left", padx=8)
    download_button = ttk.Button(panel, text="Get native stable client", command=download)
    download_button.pack(anchor="w")
    ttk.Label(panel, textvariable=status).pack(anchor="w")
    render(json.loads(read_state()))
    root.mainloop()
    executor.shutdown(wait=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("ui")
    commands.add_parser("refresh")
    commands.add_parser("list")
    commands.add_parser("fetch-native")
    addition = commands.add_parser("register")
    addition.add_argument("path")
    addition.add_argument("--track", choices=TRACKS, required=True)
    selection = commands.add_parser("select")
    selection.add_argument("id")
    args = parser.parse_args()
    try:
        if args.action == "ui":
            show_ui()
            return
        if args.action == "refresh":
            state = change_state(refresh)
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
