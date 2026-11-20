"""Record local operational events through the platform logging service."""

import logging
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from logging.handlers import SysLogHandler
from pathlib import Path

TAG = "ssh-workspace"


@lru_cache(maxsize=1)
def activity_logger():
    logger = logging.getLogger("ssh_workspace.activity")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for address in ("/dev/log", "/run/systemd/journal/dev-log"):
        if Path(address).is_socket():
            try:
                handler = SysLogHandler(address=address)
                handler.ident = f"{TAG}: "
                break
            except OSError:
                continue
    else:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(f"%(asctime)s {TAG} %(message)s"))
    logger.addHandler(handler)
    return logger


def log_activity(action, outcome, duration_ms=None):
    if duration_ms is None:
        activity_logger().info("action=%s outcome=%s", action, outcome)
    else:
        activity_logger().info("action=%s outcome=%s duration_ms=%d", action, outcome, duration_ms)


def read_history(lines=50):
    if not 1 <= lines <= 200:
        raise ValueError("Choose 1 to 200 history entries")
    command = shutil.which("journalctl")
    if command is None:
        raise ValueError("Use your operating system's syslog viewer to find ssh-workspace events")
    result = subprocess.run([
        command, "--no-pager", "--quiet", "--identifier", TAG, "--lines", str(lines),
        f"_UID={os.geteuid()}",
    ], text=True, capture_output=True, timeout=5)
    if result.returncode:
        raise ValueError("The system journal is unavailable to this account")
    return result.stdout.strip() or "No SSH Workspace events are visible in the system journal."
