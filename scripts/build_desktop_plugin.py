#!/usr/bin/env python3
"""Create an OS-specific desktop-only plugin ZIP containing the Rust SSH companion."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

TARGETS = {
    "x86_64-unknown-linux-gnu": ("linux-x64", "sshworkspace", b"\x7fELF"),
    "aarch64-unknown-linux-gnu": ("linux-arm64", "sshworkspace", b"\x7fELF"),
    "x86_64-pc-windows-msvc": ("windows-x64", "sshworkspace.exe", b"MZ"),
    "x86_64-apple-darwin": ("macos-intel", "sshworkspace", None),
    "aarch64-apple-darwin": ("macos-arm64", "sshworkspace", None),
}
MACHO = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
         b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()

def json_file(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")

def package(binary: Path, target: str, version: str, output: Path, root: Path) -> Path:
    if target not in TARGETS:
        raise ValueError("Unsupported build target")
    if not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){2}", version):
        raise ValueError("Version must be major.minor.patch")
    if not binary.is_file() or binary.is_symlink() or binary.stat().st_size < 1024:
        raise ValueError("Binary must be a regular executable with plausible size")
    label, name, magic = TARGETS[target]
    with binary.open("rb") as f:
        header = f.read(4)
    if magic and not header.startswith(magic):
        raise ValueError("Binary header does not match target")
    if magic is None and header not in MACHO:
        raise ValueError("Expected a Mach-O binary")
    output.mkdir(parents=True, exist_ok=True)
    filename = "ssh-workspace-desktop-v{}-{}.zip".format(version, label)
    archive = output / filename
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        executable = stage / "bin" / name
        executable.parent.mkdir()
        shutil.copy2(binary, executable)
        if name != "sshworkspace.exe":
            executable.chmod(0o755)
        root_placeholder = "$" + "{PLUGIN_ROOT}"
        json_file(stage / ".mcp.json", {"mcp_servers": {
            "ssh-workspace": {"command": root_placeholder + "/bin/" + name,
                              "args": ["mcp"], "cwd": root_placeholder}
        }})
        manifest = {
            "name": "ssh-workspace", "version": version,
            "description": "Local-first, read-only SSH diagnostics from a native companion.",
            "repository": "https://github.com/tishriclarin/ssh-workspace",
            "mcpServers": "./.mcp.json", "skills": "./skills/",
            "requires_local_executor": True,
            "interface": {
                "displayName": "SSH Workspace",
                "shortDescription": "Local SSH host diagnostics",
                "longDescription": "Inspect authorized SSH hosts from your own computer. Host keys are pinned. No generic shell command or credential disclosure tools.",
                "category": "Developer Tools", "capabilities": ["Read"],
                "brandColor": "#087A69",
                "defaultPrompt": ["List my saved SSH host aliases.",
                                  "Check SSH connectivity to my saved host.",
                                  "What is the OS and uptime of my saved Linux host?"]
            }
        }
        logo = root / "assets/logo.webp"
        if logo.is_file():
            (stage / "assets").mkdir()
            shutil.copy2(logo, stage / "assets/logo.webp")
            manifest["interface"].update({
                "logo": "./assets/logo.webp", "composerIcon": "./assets/logo.webp"})
        json_file(stage / ".codex-plugin/plugin.json", manifest)
        skill_path = stage / "skills/ssh-workspace/SKILL.md"
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text(
            "---\nname: ssh-workspace\ndescription: Local-first authorized SSH diagnostics.\n---\n\n"
            "# SSH Workspace\nUse only saved host aliases. Never ask for credentials in chat.\n"
            "Only fixed read-only diagnostics are available. Do not claim arbitrary shell access.\n"
            "Never disable strict SSH host-key checks.\n", encoding="utf-8")
        readme = root / "companion/README.md"
        if readme.is_file():
            shutil.copy2(readme, stage / "README.md")
        json_file(stage / "BUILD-INFO.json", {
            "version": version, "target": target,
            "binary_sha256": sha256(executable), "signed": False,
            "notice": "Development build. OS approval and signing are not bypassed."
        })
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
            for path in sorted(stage.rglob("*")):
                if not path.is_file():
                    continue
                info = zipfile.ZipInfo(path.relative_to(stage).as_posix(), (2026,1,1,0,0,0))
                info.compress_type = zipfile.ZIP_DEFLATED
                mode = 0o755 if path == executable and name != "sshworkspace.exe" else 0o644
                info.external_attr = (0o100000 | mode) << 16
                zipf.writestr(info, path.read_bytes())
    (output / (filename + ".sha256")).write_text(
        sha256(archive) + "  " + filename + "\n", encoding="ascii")
    return archive

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--target", choices=sorted(TARGETS), required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    args = p.parse_args()
    print(package(args.binary, args.target, args.version, args.output, args.repo))

if __name__ == "__main__":
    main()
