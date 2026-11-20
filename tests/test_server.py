import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError

from server import SSHClientUnavailable, ssh_args, ssh_process_args
from vault import ConnectionOptions, Host, Inventory, Vault, VaultError

ROOT = Path(__file__).resolve().parent.parent


def key_profile(**changes):
    return Host.model_validate({
        "address": "127.0.0.1", "port": 8022, "account": "diagnostics",
        "identity_file": "/keys/id", "known_hosts_file": "/keys/known_hosts",
        **changes,
    })


class VaultTests(unittest.TestCase):
    def test_profile_metadata_and_password_are_authenticated_and_encrypted(self):
        secret = "test-password"
        profile = key_profile(
            address="10.2.3.4", hostname="branch-router", group="branch-network",
            comment="my test comment", identity_file=None, password=secret, auth="password",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hosts.vault"
            key = Fernet.generate_key()
            vault = Vault(path, key)
            vault.update(lambda _: Inventory(hosts={"test-alias": profile}), initialize=True)
            encrypted = path.read_bytes()
            for value in (secret, profile.address, profile.hostname, profile.group, profile.comment, "test-alias"):
                self.assertNotIn(value.encode(), encrypted)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(vault.load().hosts["test-alias"], profile)
            with self.assertRaises(VaultError):
                Vault(path, Fernet.generate_key()).load()
            path.write_bytes(b"x" + encrypted[1:])
            with self.assertRaises(VaultError):
                vault.load()

    def test_password_is_delivered_only_through_anonymous_pipe(self):
        profile = key_profile(identity_file=None, password="test-password", auth="password")
        with patch("server.selected_executable", return_value="/test/bin/ssh"), \
             patch("server.shutil.which", return_value="/test/bin/sshpass"), \
             ssh_process_args(profile, "true") as (argv, descriptors):
            self.assertEqual(argv[:4], ["/test/bin/sshpass", "-d", str(descriptors[0]), "/test/bin/ssh"])
            self.assertNotIn("test-password", json.dumps(argv))
            self.assertEqual(os.read(descriptors[0], 100), b"test-password\n")
            self.assertIn("StrictHostKeyChecking=yes", argv)
            self.assertIn("PreferredAuthentications=password", argv)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_key_profile_reuses_ssh_from_path_without_sshpass(self):
        with patch("server.selected_executable", return_value="/local/bin/ssh") as find:
            with ssh_process_args(key_profile(), "true") as (argv, descriptors):
                self.assertEqual(argv[0], "/local/bin/ssh")
                self.assertEqual(descriptors, ())
                self.assertNotIn("ChannelTimeout=session=8s", argv)
            find.assert_called_once_with()
        with patch("server.selected_executable", return_value=None):
            with self.assertRaisesRegex(SSHClientUnavailable, "cannot find ssh on PATH"), \
                 ssh_process_args(key_profile(), "true"):
                self.fail("An SSH process cannot start without the system client")

    def test_ciphers_certificate_and_source_are_passed_as_individual_arguments(self):
        profile = key_profile(
            certificate_file="/keys/id-cert.pub", bind_address="127.0.0.2",
            ciphers=["aes256-ctr"], kex_algorithms=["curve25519-sha256"],
            macs=["hmac-sha2-256"], host_key_algorithms=["ssh-ed25519"],
            pubkey_algorithms=["ssh-ed25519-cert-v01@openssh.com"],
        )
        argv = ssh_args(profile, "uname -sm")
        for option in (
            "CertificateFile=/keys/id-cert.pub", "Ciphers=aes256-ctr",
            "KexAlgorithms=curve25519-sha256", "MACs=hmac-sha2-256",
            "HostKeyAlgorithms=ssh-ed25519", "PubkeyAcceptedKeyTypes=ssh-ed25519-cert-v01@openssh.com",
            "StrictHostKeyChecking=yes", "IdentityAgent=none",
        ):
            self.assertIn(option, argv)
        self.assertEqual(argv[argv.index("-b") + 1], "127.0.0.2")
        self.assertEqual(argv[-3:], ["--", "127.0.0.1", "uname -sm"])
        with self.assertRaises(ValidationError):
            ConnectionOptions.model_validate({"bind_address": "127.0.0.2", "bind_interface": "lo"})
        with self.assertRaises(ValidationError):
            ConnectionOptions.model_validate({"ciphers": ["aes256-ctr,none"]})


class LocalMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_reloads_vault_and_rejects_unknown_host_and_destination_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "ssh-workspace"
            config.mkdir()
            key_file = config / "vault.key"
            key_file.touch(mode=0o600)
            key_file.write_bytes(Fernet.generate_key())
            vault = Vault(config / "hosts.vault", key_file.read_bytes())
            vault.update(lambda _: Inventory(hosts={"demo-linux": key_profile(group="lab")}), initialize=True)
            params = StdioServerParameters(
                command=sys.executable, args=[str(ROOT / "launch.py")],
                env={"XDG_CONFIG_HOME": str(root)},
            )
            async with asyncio.timeout(15):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        self.assertEqual(initialized.serverInfo.name, "SSH Workspace")
                        tools = await session.list_tools()
                        self.assertEqual({tool.name for tool in tools.tools}, {
                            "list_ssh_hosts", "check_ssh_connection",
                            "get_ssh_host_platform", "get_ssh_host_uptime",
                        })
                        self.assertTrue(all(tool.annotations.readOnlyHint for tool in tools.tools))
                        for group, expected in (("lab", ["demo-linux"]), ("office", [])):
                            found = await session.call_tool("list_ssh_hosts", {"group": group})
                            self.assertEqual(found.structuredContent, {"result": expected})
                        unknown = await session.call_tool("check_ssh_connection", {"host": "unknown"})
                        self.assertTrue(unknown.isError)
                        bad = await session.call_tool("check_ssh_connection", {
                            "host": "demo-linux", "overrides": {"address": "203.0.113.1"},
                        })
                        self.assertTrue(bad.isError)
                        vault.update(lambda _: Inventory(hosts={"new-host": key_profile()}))
                        found = await session.call_tool("list_ssh_hosts", {})
                        self.assertEqual(found.structuredContent, {"result": ["new-host"]})
