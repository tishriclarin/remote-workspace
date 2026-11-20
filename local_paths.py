"""Paths shared by the local server and its administration tools."""

import os
from pathlib import Path


def config_directory() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ssh-workspace"
