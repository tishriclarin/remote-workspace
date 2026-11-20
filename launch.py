"""Launch the local MCP server with the installed workspace Python environment."""

import os
import sys
from pathlib import Path

from local_paths import config_directory

package = Path(__file__).resolve().parent
server = package / "server.py"
vendor = package / "vendor"
local_python = config_directory() / "venv/bin/python"
imports = [str(package)]
if vendor.is_dir():
    imports.append(str(vendor))
python = str(local_python) if not vendor.is_dir() and local_python.is_file() else sys.executable
bootstrap = (
    "import runpy, sys; "
    "sys.path[:0] = sys.argv[2:]; "
    "runpy.run_path(sys.argv[1], run_name='__main__')"
)
os.execv(python, [python, "-I", "-c", bootstrap, str(server), *imports])
