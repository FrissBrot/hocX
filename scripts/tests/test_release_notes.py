import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "release_notes", Path(__file__).resolve().parents[1] / "release_notes.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseNotesTests(unittest.TestCase):
    def test_only_requested_version_with_nested_headings(self):
        changelog = "# Changelog\n\n## [Unveröffentlicht]\nZukunft\n\n## [1.2.0] - 2026-09-22\n\n### Neu\n- Änderung\n\n## [1.1.0]\nAlt\n"
        expected = "## [1.2.0] - 2026-09-22\n\n### Neu\n- Änderung\n"
        for tag in ["v1.2.0", "1.2.0"]:
            self.assertEqual(module.release_notes(changelog, tag), expected)

    def test_missing_empty_duplicate_and_invalid_fail(self):
        for changelog, tag in [
            ("## [1.2.01]\nFalsch", "v1.2.0"),
            ("## [1.2.0]\n\n## [1.1.0]\nAlt", "v1.2.0"),
            ("## [1.2.0]\nA\n## [1.2.0]\nB", "v1.2.0"),
            ("## [Unveröffentlicht]\nZukunft", "latest"),
        ]:
            with self.subTest(changelog=changelog, tag=tag), self.assertRaises(ValueError):
                module.release_notes(changelog, tag)
