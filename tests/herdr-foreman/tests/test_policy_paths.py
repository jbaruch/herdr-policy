"""An extracted Herdr runtime reaches one compatible general helper bundle."""

import sys as _test_sys
from pathlib import Path as _TestPath
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str((Path(__file__).resolve().parents[3] / "skills/herdr-foreman")))

from foreman.errors import UsageError
from foreman.policy_paths import NATIVE_FOREMAN, NATIVE_RELEASE, RELEASE_FILES, WORKFLOW_RELEASE_FILES, brief_inputs, coding_release, require_workflow_release


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

    def test_task_workflow_requires_independent_reviews_in_the_selected_bundle(self):
        local = self.bundle(self.shared / ".tessl/plugins/jbaruch/coding-policy/skills/release")
        other = self.bundle(self.global_tessl / "plugins/jbaruch/coding-policy/skills/release")
        for name in WORKFLOW_RELEASE_FILES:
            (other / name).write_text("Other installation's helper.\n")
        with self.assertRaisesRegex(UsageError, "0.5.0") as caught:
            require_workflow_release(self.resolve())
        self.assertIn("review-lanes.sh", caught.exception.details["missing"])
        for name in WORKFLOW_RELEASE_FILES:
            (local / name).write_text("Selected installation's helper.\n")
        self.assertEqual(require_workflow_release(self.resolve()), local)

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

    def test_combined_legacy_plugins_refuse_even_when_new_helpers_are_available(self):
        self.bundle(self.shared / ".tessl/plugins/jbaruch/coding-policy/skills/release")
        explicit = self.root / "coding-source"
        self.bundle(explicit / "skills/release")
        for package in (self.shared / ".tessl/plugins/jbaruch/coding-policy",
                        self.global_tessl / "plugins/jbaruch/coding-policy"):
            legacy = package / "skills/herdr-foreman"
            legacy.mkdir(parents=True)
            with self.subTest(package=package), self.assertRaisesRegex(UsageError, "combined"):
                self.resolve(explicit)
            legacy.rmdir()

    def test_executing_tessl_package_peer_cannot_hide_a_legacy_registration(self):
        self.skill = self.root / "other/.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman"
        self.skill.mkdir(parents=True)
        legacy = self.skill.parents[2] / "coding-policy/skills/herdr-foreman"
        legacy.mkdir(parents=True)
        self.bundle(self.shared / ".tessl/plugins/jbaruch/coding-policy/skills/release")
        with self.assertRaisesRegex(UsageError, "combined"):
            self.resolve()

    def test_unregistered_source_helpers_do_not_count_as_installed_team_hooks(self):
        source = self.root / "coding-source"
        expected = self.bundle(source / "skills/release")
        (source / "skills/herdr-foreman").mkdir()
        self.assertEqual(self.resolve(source), expected)

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

    def test_native_policy_uses_its_package_router_instead_of_unrelated_instructions(self):
        for host in (".codex/skills", ".claude/skills", ".cursor/skills", ".agents/skills"):
            with self.subTest(host=host):
                skill = self.shared / host / NATIVE_FOREMAN
                (skill / "references").mkdir(parents=True)
                (skill / "references/worker-context.md").write_text("executing team contract\n")
                release = self.bundle(skill.parent / NATIVE_RELEASE)
                (release / "POLICY.md").write_text("package-native policy routing\n")
                (self.shared / "AGENTS.md").write_text("unrelated user instructions\n")
                result = brief_inputs(skill, self.shared, self.global_tessl)
                self.assertEqual(result["POLICY_INDEX"], str(release / "POLICY.md"))
                self.assertEqual(result["TEAM_OPERATION"], str((skill / "references/worker-context.md").resolve()))
                (release / "POLICY.md").unlink()
                with self.assertRaises(UsageError):
                    brief_inputs(skill, self.shared, self.global_tessl)


    def identity_cli(self, shared=None):
        script = Path(__file__).resolve().parents[3] / "skills/herdr-foreman/policy-paths.py"
        return subprocess.run([sys.executable, str(script), "identity", "--shared", str(shared or self.shared),
            "--global-tessl", str(self.global_tessl)], cwd=self.shared, capture_output=True, text=True)

    def test_source_identity_cli_reports_its_actual_package_without_dispatch(self):
        result = self.identity_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        root = Path(__file__).resolve().parents[3]
        value = json.loads(result.stdout)
        self.assertEqual(value["policy_root"], str(root))
        self.assertEqual(value["version"], json.loads((root / ".tessl-plugin/plugin.json").read_text())["version"])
        self.assertRegex(value["digest"], r"^[a-f0-9]{64}$")
        self.assertIs(value["authorizes_dispatch"], False)
        self.assertEqual(list(self.shared.iterdir()), [])

    def test_identity_cli_refuses_invalid_selection_with_no_success_json(self):
        result = self.identity_cli(self.root / "missing")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("policy-paths:", result.stderr)
        self.assertIn("repair", result.stderr)
        self.assertEqual(list(self.shared.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
