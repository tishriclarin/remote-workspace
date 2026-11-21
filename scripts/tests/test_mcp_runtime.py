#!/usr/bin/env python3
"""Exercise the compiled native MCP server with disposable local configuration."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BINARY = os.getenv("SSHWORKSPACE_BIN")

@unittest.skipUnless(BINARY and Path(BINARY).is_file(), "Requires SSHWORKSPACE_BIN")
class MCPRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = dict(os.environ)
        self.env["SSHWORKSPACE_HOME"] = self.temp.name
        result = subprocess.run([BINARY, "setup"], env=self.env, capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def request(self, *messages):
        input_data = "".join(json.dumps(r) + "\n" for r in messages)
        process = subprocess.run([BINARY, "mcp"], env=self.env, input=input_data,
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        return [json.loads(x) for x in process.stdout.splitlines()]

    def test_handshake_and_tools(self):
        result = self.request(
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
                "protocolVersion":"2025-03-26","capabilities":{},
                "clientInfo":{"name":"ci-smoke","version":"1.0"}}},
            {"jsonrpc":"2.0","method":"notifications/initialized"},
            {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}},
            {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
                "name":"get_gateway_status","arguments":{}}},
            {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{
                "name":"list_ssh_hosts","arguments":{}}},
        )
        self.assertEqual([m["id"] for m in result], [1,2,3,4])
        self.assertEqual(result[0]["result"]["protocolVersion"], "2025-03-26")
        tools = result[1]["result"]["tools"]
        self.assertEqual(len(tools), 6)
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in tools))
        self.assertFalse(any(t["name"] == "run_command" for t in tools))
        status = json.loads(result[2]["result"]["content"][0]["text"])
        self.assertEqual(status["gateway_mode"], "client")
        self.assertTrue(status["read_only"])
        self.assertEqual(status["transport"], "local_stdio")
        hosts = json.loads(result[3]["result"]["content"][0]["text"])
        self.assertEqual(hosts["aliases"], [])

    def test_unknown_command_and_alias_rejected(self):
        result = self.request(
            {"jsonrpc":"2.0","id":5,"method":"tools/call","params":{
                "name":"run_command","arguments":{"command":"whoami"}}},
            {"jsonrpc":"2.0","id":6,"method":"tools/call","params":{
                "name":"check_ssh_connection","arguments":{"alias":"../unsafe"}}},
        )
        self.assertEqual(len(result), 2)
        self.assertTrue(all(m["result"]["isError"] for m in result))

    def test_host_list_does_not_expose_addresses(self):
        entry = subprocess.run([BINARY,"host","add","branch","192.0.2.22","operator"],
                               env=self.env,text=True,capture_output=True,timeout=20)
        self.assertEqual(entry.returncode,0,entry.stderr)
        result=self.request({"jsonrpc":"2.0","id":7,"method":"tools/call",
                             "params":{"name":"list_ssh_hosts","arguments":{}}})
        self.assertEqual(json.loads(result[0]["result"]["content"][0]["text"]),
                         {"aliases":["branch"]})
        self.assertNotIn("192.0.2.22", json.dumps(result))

    def test_user_owned_install_does_not_require_administrator(self):
        dest = Path(self.temp.name) / "native-install"
        env = {**self.env, "SSHWORKSPACE_INSTALL_ROOT": str(dest)}
        result = subprocess.run([BINARY,"install","--user"],env=env,
                                capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        name = "sshworkspace.exe" if os.name == "nt" else "sshworkspace"
        self.assertTrue((dest / name).is_file())
        self.assertIn("Installed SSH Workspace",result.stdout)

    def test_central_mode_is_explicit(self):
        result = subprocess.run([BINARY, "gateway", "central", "https://example.invalid/mcp"],
                                env=self.env, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([BINARY, "status"], env=self.env,
                                text=True, capture_output=True, timeout=20)
        self.assertIn('"gateway_mode": "central"', result.stdout)
        result = subprocess.run([BINARY, "gateway", "client"], env=self.env,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == "__main__":
    unittest.main()
