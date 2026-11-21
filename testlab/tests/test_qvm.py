"""Unit tests for qvm snapshot description/timestamps and selection."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

MODULE = Path(__file__).resolve().parent.parent / "qvm.py"
spec = importlib.util.spec_from_file_location("ssh_workspace_qvm", MODULE)
qvm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qvm)


class QvmMetadataTests(unittest.TestCase):
    def test_description_and_timestamp(self):
        label, local, utc = qvm.snapshot_name(
            "a simulation of radius server",
            datetime(2026, 11, 21, 8, 44, 22, tzinfo=timezone(timedelta(hours=8)))
        )
        self.assertRegex(label, r"^20261121-084422-a-simulation-of-radius-server-[0-9a-f]{8}$")
        self.assertEqual(local, "2026-11-21T08:44:22+08:00")
        self.assertEqual(utc, "2026-11-21T00:44:22+00:00")

    def test_control_characters_rejected(self):
        for bad in ("", "   ", "bad\nname", "x" * 201):
            with self.subTest(bad=bad):
                with self.assertRaises(qvm.QVMError):
                    qvm.snapshot_name(bad)

    def test_names_cannot_escape_paths(self):
        label, _, _ = qvm.snapshot_name("../../evade **/: drive")
        self.assertNotIn("/", label)
        self.assertNotIn("*", label)

    def test_archive_listing_returns_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / "lab-20261121-084422-sim-12345678.json"
            record = {
                "vm": "lab", "description": "a simulation of radius server",
                "saved_at_local": "2026-11-21T08:44:22+08:00",
                "saved_disk": "lab.qcow2"
            }
            data.write_text(json.dumps(record))
            entries = qvm.snapshot_list("lab", {"archives": root})
            self.assertEqual(entries[0]["description"], record["description"])
            self.assertEqual(entries[0]["saved_at_local"], record["saved_at_local"])

    def test_selects_default_machine(self):
        config = {
            "default_vm": "linux-lab",
            "machines": {"linux-lab": {
                "backend": "libvirt-qcow2", "domain": "linux-lab",
                "disk": "/tmp/a.qcow2", "template": "/tmp/b.qcow2",
                "archives": "/tmp/arch"
            }}
        }
        name, vm = qvm.get_machine(config, None)
        self.assertEqual(name, "linux-lab")
        self.assertEqual(vm["domain"], "linux-lab")


if __name__ == "__main__":
    unittest.main()
