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
        (self.root / "NOTICE").write_text("Remote Workspace\\n")
        for skill in ("remote-safety", "remote-workspace", "ssh-client", "device-inventory", "vendor-mikrotik",
                      "vendor-cisco", "vendor-juniper", "vendor-huawei",
                      "vendor-zte", "telnet-legacy"):
            target = self.root / "skills" / skill / "SKILL.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Test skill\n", encoding="utf-8")
        self.binary = self.root / "remoteworkspace"
        self.binary.write_bytes(b"\x7fELF" + b"\0" * 2048)

    def test_local_native_plugin_archive(self):
        path = package_module.package(self.binary, "x86_64-unknown-linux-gnu",
                                      "0.7.0", self.root / "dist", self.root)
        self.assertTrue(Path(str(path) + ".sha256").exists())
        with zipfile.ZipFile(path) as zipf:
            names = zipf.namelist()
            for name in ["plugin.json", "mcp.json", ".codex-plugin/plugin.json", ".mcp.json", "bin/remoteworkspace", "LICENSE", "NOTICE", "skills/vendor-mikrotik/SKILL.md", "skills/telnet-legacy/SKILL.md",
                         "skills/remote-workspace/SKILL.md", "BUILD-INFO.json"]:
                self.assertIn(name, names)
            manifest = json.loads(zipf.read(".codex-plugin/plugin.json"))
            conf = json.loads(zipf.read("mcp.json"))
            self.assertEqual(conf, json.loads(zipf.read(".mcp.json")))
            self.assertEqual(conf["mcpServers"]["remote-workspace"]["type"], "stdio")
            root_manifest = json.loads(zipf.read("plugin.json"))
            self.assertEqual(root_manifest["name"], "remote-workspace")
            self.assertTrue(root_manifest["extensions"]["com.openai"]["requires_local_executor"])
            info = json.loads(zipf.read("BUILD-INFO.json"))
            self.assertEqual(manifest["version"], "0.7.0")
            self.assertEqual(conf["mcpServers"]["remote-workspace"]["command"],
                             "$" + "{PLUGIN_ROOT}/bin/remoteworkspace")
            self.assertTrue(manifest["requires_local_executor"])
            self.assertEqual(manifest["mcpServers"], "./.mcp.json")
            self.assertEqual(conf["mcpServers"]["remote-workspace"]["args"], ["mcp"])
            self.assertFalse(info["signed"])
            self.assertTrue(zipf.getinfo("bin/remoteworkspace").external_attr >> 16 & 0o111)

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
