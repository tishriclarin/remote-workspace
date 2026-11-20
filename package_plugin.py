"""Build the local SSH Workspace plugin ZIP."""

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
FILES = (
    "mcp.json", "README.md", "requirements.txt", "launch.py", "local_paths.py", "server.py",
    "vault.py", "vault_admin.py", "ssh-diagnostics.sh", "assets/logo.webp",
    "package_plugin.py", "tests/test_server.py",
    "activity.py", "ssh_clients.py", "settings_ui.py", "enroll.py", "tests/test_clients_and_enroll.py",
    "RELEASE-REVIEW.md",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publisher", help="Verified developer name for directory review")
    parser.add_argument("--vendor", type=Path, help="Dependencies for the target Python version and OS")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "plugin.json").read_text())
    if args.publisher is not None:
        publisher = args.publisher.strip()
        if not 1 <= len(publisher) <= 80:
            parser.error("Publisher must have between 1 and 80 characters")
        manifest["author"] = {"name": publisher}
        manifest["extensions"]["com.openai"]["interface"]["developerName"] = publisher
    if args.vendor and not all((args.vendor / name).is_dir() for name in ("mcp", "cryptography", "pydantic")):
        parser.error("Vendor directory must contain the installed Python dependencies")
    with ZipFile(args.output, "x", compression=ZIP_DEFLATED) as archive:
        archive.writestr("plugin.json", json.dumps(manifest, indent=2) + "\n")
        for name in FILES:
            archive.write(ROOT / name, name)
        if args.vendor:
            for path in sorted(args.vendor.rglob("*")):
                relative = path.relative_to(args.vendor)
                if path.is_file() and "__pycache__" not in relative.parts:
                    archive.write(path, Path("vendor") / relative)


if __name__ == "__main__":
    main()
