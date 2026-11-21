#!/usr/bin/env python3
"""Local SSH integration test: real sshd with key pinning and a disposable account."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

BIN = os.getenv("REMOTEWORKSPACE_BIN")
SSHD = shutil.which("sshd") or ("/usr/sbin/sshd" if Path("/usr/sbin/sshd").is_file() else None)
KEYGEN = shutil.which("ssh-keygen")

@unittest.skipUnless(BIN and SSHD and KEYGEN and os.name != "nt",
                     "Requires a compiled companion and a local OpenSSH server")
class LiveSSHTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.env = dict(os.environ)
        self.env.update({"REMOTEWORKSPACE_HOME":str(self.dir / "cfg"),"HOME":str(self.dir)})
        ssh_dir = self.dir / ".ssh"
        ssh_dir.mkdir(mode=0o700)
        self.hostkey = self.dir / "ssh_host_ed25519_key"
        self.userkey = self.dir / "client_ed25519"
        for key in (self.hostkey, self.userkey):
            run = subprocess.run([KEYGEN,"-q","-t","ed25519","-N","","-f",str(key)],
                                 capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr)
        authorized = self.dir / "authorized_keys"
        authorized.write_text(Path(str(self.userkey)+".pub").read_text())
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            self.port = sock.getsockname()[1]
        user = os.environ.get("USER") or subprocess.check_output(["id","-un"],text=True).strip()
        self.user = user
        config = self.dir / "sshd_config"
        config.write_text("\n".join([
            f"Port {self.port}", "ListenAddress 127.0.0.1",
            f"HostKey {self.hostkey}", f"AuthorizedKeysFile {authorized}",
            "PasswordAuthentication no", "KbdInteractiveAuthentication no",
            "PubkeyAuthentication yes", "UsePAM no", "StrictModes no",
            "LogLevel ERROR", f"PidFile {self.dir / 'sshd.pid'}",
            "Subsystem sftp internal-sftp"
        ])+"\n")
        self.daemon = subprocess.Popen([SSHD,"-D","-e","-f",str(config)],
                                       stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE,text=True)
        self.addCleanup(self.cleanup_daemon)
        for _ in range(50):
            if self.daemon.poll() is not None:
                self.fail("sshd terminated before tests: "+self.daemon.stderr.read())
            try:
                with socket.create_connection(("127.0.0.1",self.port),timeout=.1):
                    break
            except OSError:
                time.sleep(.1)
        else:
            self.fail("sshd fixture never listened")
        pub_fields = Path(str(self.hostkey)+".pub").read_text().strip().split()
        (ssh_dir / "known_hosts").write_text(
            f"[127.0.0.1]:{self.port} {pub_fields[0]} {pub_fields[1]}\n")
        setup = subprocess.run([BIN, "setup"],env=self.env,text=True,capture_output=True,timeout=15)
        self.assertEqual(setup.returncode,0,setup.stderr)
        saved = subprocess.run([BIN,"host","add","ci-local","127.0.0.1",self.user,
                                str(self.port),str(self.userkey)],env=self.env,
                               text=True,capture_output=True,timeout=15)
        self.assertEqual(saved.returncode,0,saved.stderr)

    def cleanup_daemon(self):
        if self.daemon.poll() is None:
            self.daemon.terminate()
            try:self.daemon.wait(timeout=5)
            except subprocess.TimeoutExpired:self.daemon.kill()

    def request(self, name):
        msg = json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call",
                          "params":{"name":name,"arguments":{"alias":"ci-local"}}})+"\n"
        p = subprocess.run([BIN,"mcp"],env=self.env,input=msg,text=True,
                           capture_output=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(p.stdout.strip())["result"]

    def test_connect_platform_uptime_and_host_key_rejection(self):
        result = self.request("check_ssh_connection")
        self.assertFalse(result["isError"],result)
        response = json.loads(result["content"][0]["text"])
        self.assertEqual(response["status"],"connected")
        result = self.request("get_ssh_host_platform")
        self.assertFalse(result["isError"],result)
        self.assertIn("Linux",result["content"][0]["text"])
        result = self.request("get_ssh_host_uptime")
        self.assertFalse(result["isError"],result)
        self.assertIn("uptime_seconds",result["content"][0]["text"])
        (self.dir / ".ssh" / "known_hosts").write_text("")
        result = self.request("check_ssh_connection")
        self.assertTrue(result["isError"],result)

if __name__ == "__main__":
    unittest.main()
