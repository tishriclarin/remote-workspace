import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ssh_clients
from enroll import CA_INSTALL, ca_entry


class ClientCacheTests(unittest.TestCase):
    def test_refresh_retains_highest_version_of_four_majors_per_track(self):
        state = {"registered": [
            {"path": f"/test/{track}/{major}.1", "track": track}
            for track in ssh_clients.TRACKS for major in range(6, 11)
        ] + [{"path": "/test/stable/10.2", "track": "stable"}], "cache": []}

        def inspect(path, track):
            version = path.rsplit("/", 1)[1]
            return {"id": f"{track}:{path}", "path": path, "track": track,
                    "version": version, "order": list(map(int, version.split("."))) + [0]}

        with patch.object(ssh_clients.shutil, "which", return_value=None), \
             patch.object(ssh_clients, "inspect_client", side_effect=inspect), \
             patch.object(ssh_clients.os, "access", return_value=True):
            ssh_clients.refresh(state)
            for track in ssh_clients.TRACKS:
                versions = [client["order"][0] for client in state["cache"] if client["track"] == track]
                self.assertEqual(versions, [10, 9, 8, 7])
            state["selection"] = "latest"
            with patch.object(ssh_clients, "read_state", side_effect=lambda: json.dumps(state)):
                self.assertEqual(ssh_clients.selected_executable(), "/test/stable/10.2")
                state["selection"] = "development:/test/development/10.1"
                self.assertEqual(ssh_clients.selected_executable(), "/test/development/10.1")

    @unittest.skipUnless(shutil.which("dpkg-deb") and shutil.which("ssh"), "requires dpkg and OpenSSH")
    def test_native_download_selects_cpu_and_extracts_only_one_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            machine = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
            image = root / "image"
            (image / "DEBIAN").mkdir(parents=True)
            (image / "usr/bin").mkdir(parents=True)
            shutil.copy2(shutil.which("ssh"), image / "usr/bin/ssh")
            (image / "DEBIAN/control").write_text(
                f"Package: openssh-client\nVersion: 99.0\nArchitecture: {machine}\n"
                "Maintainer: Test <test@example.invalid>\nDescription: Test fixture\n"
            )
            deb = root / "fixture.deb"
            subprocess.run(["dpkg-deb", "--build", image, deb], check=True, capture_output=True)
            real_run = subprocess.run

            def apt_fixture(argv, **kwargs):
                if Path(argv[0]).name == "apt-get":
                    self.assertEqual(argv[-2:], ["download", f"openssh-client:{machine}"])
                    shutil.copy2(deb, Path(kwargs["cwd"]) / "fixture.deb")
                    return subprocess.CompletedProcess(argv, 0)
                return real_run(argv, **kwargs)

            with patch.object(ssh_clients, "config_directory", return_value=root / "config"), \
                 patch.object(ssh_clients.subprocess, "run", side_effect=apt_fixture):
                for _ in range(2):
                    state = ssh_clients.fetch_native()
                managed = list((root / "config/native-clients").rglob("ssh"))
                self.assertEqual(len(managed), 1)
                self.assertEqual(state["registered"][0]["path"], str(managed[0]))
                self.assertEqual(ssh_clients.selected_executable(), str(managed[0]))


@unittest.skipUnless(shutil.which("ssh-keygen") and shutil.which("flock"), "requires native OpenSSH and flock")
class CertificateEnrollmentTests(unittest.TestCase):
    def test_only_matching_ca_and_principal_are_installed_and_retry_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            ca, user, wrong = [home / name for name in ("ca", "user", "wrong")]
            for path in (ca, user, wrong):
                subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", path], check=True)
            ca_public = ca.with_suffix(".pub")
            subprocess.run([
                "ssh-keygen", "-q", "-s", ca, "-I", "test", "-n", "operator", "-V", "+1h",
                user.with_suffix(".pub"),
            ], check=True)
            certificate = home / "user-cert.pub"
            with self.assertRaisesRegex(ValueError, "different CA"):
                ca_entry(wrong.with_suffix(".pub"), certificate, "operator", "ssh-keygen")
            with self.assertRaisesRegex(ValueError, "does not include"):
                ca_entry(ca_public, certificate, "someone-else", "ssh-keygen")
            line = ca_entry(ca_public, certificate, "operator", "ssh-keygen")
            self.assertTrue(line.startswith('cert-authority,restrict,principals="operator" ssh-ed25519 '))
            for _ in range(2):
                subprocess.run(["sh", "-c", CA_INSTALL], input=line + "\n", text=True,
                               env={**os.environ, "HOME": str(home)}, check=True)
            authorized = home / ".ssh/authorized_keys"
            self.assertEqual([entry for entry in authorized.read_text().splitlines() if entry], [line])
            self.assertEqual(authorized.stat().st_mode & 0o777, 0o600)
