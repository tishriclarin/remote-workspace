"""Launch the local MCP server with the installed workspace Python environment."""

import os
import sys
from pathlib import Path

from local_paths import config_directory

package = Path(__file__).resolve().parent
server = package / "server.py"
vendor = package / "vendor"
local_python = config_directory() / "venv/bin/python"
if vendor.is_dir():
    imports = [str(vendor)]
    if os.environ.get("PYTHONPATH"):
        imports.append(os.environ["PYTHONPATH"])
    os.environ["PYTHONPATH"] = os.pathsep.join(imports)
    python = sys.executable
else:
    python = str(local_python) if local_python.is_file() else sys.executable
os.execv(python, [python, str(server)])
