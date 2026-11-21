#!/usr/bin/env python3
"""Validate that the generated desktop plugin ZIP contains a working native MCP server."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ARCHIVE_DIR = Path(os.environ.get("REMOTEWORKSPACE_ARCHIVES", "dist"))

class ArchiveRuntimeTest(unittest.TestCase):
    def test_generated_zip_can_launch_native_mcp(self):
        matches = list(ARCHIVE_DIR.glob("remote-workspace-desktop-v*.zip"))
        self.assertEqual(len(matches), 1, "Expected exactly one desktop plugin archive")
        with zipfile.ZipFile(matches[0]) as archive:
            paths = archive.namelist()
            self.assertTrue(all(not p.startswith("/") and ".." not in Path(p).parts for p in paths))
            plugin = json.loads(archive.read(".codex-plugin/plugin.json"))
            portable = json.loads(archive.read("plugin.json"))
            mcp = json.loads(archive.read("mcp.json"))
            self.assertEqual(mcp, json.loads(archive.read(".mcp.json")))
            self.assertTrue(portable["extensions"]["com.openai"]["requires_local_executor"])
            self.assertEqual(mcp["mcpServers"]["remote-workspace"]["type"], "stdio")
            self.assertEqual(plugin["mcpServers"], "./.mcp.json")
            self.assertEqual(plugin["name"], "remote-workspace")
            self.assertTrue(plugin["requires_local_executor"])
            with tempfile.TemporaryDirectory() as work:
                folder = Path(work)
                archive.extractall(folder)
                command = mcp["mcpServers"]["remote-workspace"]
                prefix = "$" + "{PLUGIN_ROOT}"
                self.assertTrue(command["command"].startswith(prefix + "/bin/"))
                relative = command["command"][len(prefix) + 1:]
                exe = folder / relative
                self.assertTrue(exe.is_file())
                if os.name != "nt":
                    exe.chmod(exe.stat().st_mode | 0o700)
                self.assertTrue(str(exe).endswith(".exe") if os.name == "nt"
                                else exe.name == "remoteworkspace")
                self.assertEqual(command["args"], ["mcp"])
                env = dict(os.environ)
                env["REMOTEWORKSPACE_HOME"] = str(folder / "private-config")
                msg = json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize",
                                  "params":{"protocolVersion":"2025-03-26",
                                            "capabilities":{},
                                            "clientInfo":{"name":"archive-ci","version":"1.0"}}}) + "\n"
                run = subprocess.run([str(exe),"mcp"],input=msg,env=env,
                                     text=True,capture_output=True,timeout=30)
                self.assertEqual(run.returncode,0,run.stderr)
                response=json.loads(run.stdout.strip())
                self.assertEqual(response["id"],1)
                self.assertEqual(response["result"]["serverInfo"]["name"],
                                 "remote-workspace-companion")

if __name__ == "__main__":
    unittest.main()
