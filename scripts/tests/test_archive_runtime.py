#!/usr/bin/env python3
"""Validate that the generated desktop plugin ZIP contains a working native MCP server."""
import json
import os
from pathlib import Path
import subprocess
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
                name = "remoteworkspace.exe" if os.name == "nt" else "remoteworkspace"
                self.assertEqual(command["command"], f"./bin/{name}")
                self.assertEqual(command["cwd"], "./")
                self.assertEqual(command["args"], ["mcp"])
                exe = folder / command["command"]
                self.assertTrue(exe.is_file())
                if os.name != "nt":
                    mode = archive.getinfo(f"bin/{name}").external_attr >> 16 & 0o777
                    self.assertTrue(mode & 0o100)
                    exe.chmod(mode)
                env = dict(os.environ)
                env["REMOTEWORKSPACE_HOME"] = str(folder / "private-config")
                requests = [
                    {"id": 1, "method": "initialize", "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "archive-ci", "version": "1.0"},
                    }},
                    {"method": "notifications/initialized"},
                    {"id": 2, "method": "tools/list"},
                    {"id": 3, "method": "tools/call", "params": {
                        "name": "list_ssh_hosts", "arguments": {},
                    }},
                ]
                messages = "".join(
                    json.dumps({"jsonrpc": "2.0", **request}) + "\n"
                    for request in requests
                )
                run = subprocess.run(
                    [str(exe), *command["args"]], input=messages, env=env, cwd=folder,
                    text=True, capture_output=True, timeout=30,
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                initialized, listed, hosts = map(json.loads, run.stdout.splitlines())
                self.assertEqual([reply["id"] for reply in (initialized, listed, hosts)], [1, 2, 3])
                self.assertEqual(initialized["result"]["serverInfo"]["name"],
                                 "remote-workspace-companion")
                tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
                self.assertTrue(tools["list_ssh_hosts"]["annotations"]["readOnlyHint"])
                self.assertFalse(hosts["result"]["isError"])
                self.assertEqual(json.loads(hosts["result"]["content"][0]["text"]),
                                 {"aliases": []})

if __name__ == "__main__":
    unittest.main()
