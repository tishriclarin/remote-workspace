#!/usr/bin/env python3
"""Check that documentation editor assets and mandatory policies ship together."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

class InstallerDocumentationTests(unittest.TestCase):
    def test_documentation_script_is_staged_by_ci(self):
        workflow = (ROOT / ".github/workflows/companion-build.yml").read_text()
        self.assertIn("../installer/docs.js dist/installer/", workflow,
                      "Documentation editor is referenced by setup.html but absent from CI deliverable")

    def test_editor_script_is_referenced(self):
        html = (ROOT / "installer/setup.html").read_text()
        self.assertIn('src="docs.js"', html)
        self.assertTrue((ROOT / "installer/docs.js").is_file())

    def test_mandatory_safety_rules_exist(self):
        for name in ("remote-safety", "remote-workspace"):
            self.assertTrue((ROOT / "skills" / name / "SKILL.md").is_file())

if __name__ == "__main__":
    unittest.main()
