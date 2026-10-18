"""An extracted Herdr runtime reaches one compatible general helper bundle."""

import sys as _test_sys
from pathlib import Path as _TestPath
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str((Path(__file__).resolve().parents[3] / "skills/herdr-foreman")))

from foreman.errors import UsageError
from foreman.policy_paths import NATIVE_FOREMAN, NATIVE_RELEASE, RELEASE_FILES, coding_release


class PolicyPathsTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.shared = self.root / "consumer"
        self.shared.mkdir()
        self.global_tessl = self.root / "global-tessl"
        self.skill = self.root / "source/herdr-policy/skills/herdr-foreman"
        self.skill.mkdir(parents=True)

    def bundle(self, path):
        for filename in RELEASE_FILES:
            target = path / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture\n")
        return path.resolve()

    def resolve(self, explicit=None):
        return coding_release(self.skill, self.shared, self.global_tessl, explicit)

    def test_local_tessl_bundle_precedes_global(self):
        local = self.bundle(self.shared / ".tessl/plugins/jbaruch/coding-policy/skills/release")
        self.bundle(self.global_tessl / "plugins/jbaruch/coding-policy/skills/release")
        self.assertEqual(self.resolve(), local)

    def test_global_tessl_bundle_is_available_without_a_local_install(self):
        expected = self.bundle(self.global_tessl / "plugins/jbaruch/coding-policy/skills/release")
        self.assertEqual(self.resolve(), expected)

    def test_tessl_package_peer_matches_the_executing_installation(self):
        self.skill = self.shared / ".tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman"
        self.skill.mkdir(parents=True)
        expected = self.bundle(self.shared / ".tessl/plugins/jbaruch/coding-policy/skills/release")
        self.assertEqual(self.resolve(), expected)

    def test_native_bundle_uses_the_same_agent_host(self):
        for host in (".codex/skills", ".claude/skills", ".cursor/skills", ".agents/skills"):
            with self.subTest(host=host):
                self.skill = self.shared / host / NATIVE_FOREMAN
                self.skill.mkdir(parents=True)
                expected = self.bundle(self.shared / host / NATIVE_RELEASE)
                self.assertEqual(self.resolve(), expected)

    def test_explicit_source_root_does_not_select_an_installed_copy(self):
        self.bundle(self.shared / ".tessl/plugins/jbaruch/coding-policy/skills/release")
        expected = self.bundle(self.root / "coding-source/skills/release")
        self.assertEqual(self.resolve(self.root / "coding-source"), expected)

    def test_an_incomplete_bundle_never_borrows_a_missing_file_from_global(self):
        local = self.bundle(self.shared / ".tessl/plugins/jbaruch/coding-policy/skills/release")
        (local / "lib/prune_result.py").unlink()
        self.bundle(self.global_tessl / "plugins/jbaruch/coding-policy/skills/release")
        with self.assertRaises(UsageError) as caught:
            self.resolve()
        self.assertEqual(caught.exception.details["missing"], ["lib/prune_result.py"])

    def test_an_absent_explicit_root_never_falls_back_to_an_installed_copy(self):
        self.bundle(self.shared / ".tessl/plugins/jbaruch/coding-policy/skills/release")
        with self.assertRaises(UsageError):
            self.resolve(self.root / "missing")

    def test_no_package_produces_an_actionable_refusal(self):
        with self.assertRaises(UsageError) as caught:
            self.resolve()
        self.assertIn("install", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
