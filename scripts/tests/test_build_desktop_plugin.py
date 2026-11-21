import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

source = Path(__file__).resolve().parents[1] / "build_desktop_plugin.py"
spec = importlib.util.spec_from_file_location("build_desktop_plugin", source)
package_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_module)

class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "LICENSE").write_text("MIT License\\n")
        (self.root / "NOTICE").write_text("SSH Workspace\\n")
        self.binary = self.root / "sshworkspace"
        self.binary.write_bytes(b"\x7fELF" + b"\0" * 2048)

    def test_local_native_plugin_archive(self):
        path = package_module.package(self.binary, "x86_64-unknown-linux-gnu",
                                      "0.7.0", self.root / "dist", self.root)
        self.assertTrue(Path(str(path) + ".sha256").exists())
        with zipfile.ZipFile(path) as zipf:
            names = zipf.namelist()
            for name in [".codex-plugin/plugin.json", ".mcp.json", "bin/sshworkspace", "LICENSE", "NOTICE",
                         "skills/ssh-workspace/SKILL.md", "BUILD-INFO.json"]:
                self.assertIn(name, names)
            manifest = json.loads(zipf.read(".codex-plugin/plugin.json"))
            conf = json.loads(zipf.read(".mcp.json"))
            info = json.loads(zipf.read("BUILD-INFO.json"))
            self.assertEqual(manifest["version"], "0.7.0")
            self.assertEqual(conf["mcp_servers"]["ssh-workspace"]["command"],
                             "$" + "{PLUGIN_ROOT}/bin/sshworkspace")
            self.assertTrue(manifest["requires_local_executor"])
            self.assertFalse(info["signed"])
            self.assertTrue(zipf.getinfo("bin/sshworkspace").external_attr >> 16 & 0o111)

    def test_rejects_wrong_target(self):
        with self.assertRaisesRegex(ValueError, "header"):
            package_module.package(self.binary, "x86_64-pc-windows-msvc",
                                   "0.7.0", self.root / "dist", self.root)

    def test_rejects_symlink(self):
        link = self.root / "link"
        link.symlink_to(self.binary)
        with self.assertRaisesRegex(ValueError, "regular"):
            package_module.package(link, "x86_64-unknown-linux-gnu",
                                   "0.7.0", self.root / "dist", self.root)

if __name__ == "__main__":
    unittest.main()
