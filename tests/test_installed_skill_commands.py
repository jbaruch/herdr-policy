"""Installed command checks reject missing, foreign and unusable native roots."""

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installation_check", ROOT / "scripts/check-installations.py")
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class InstalledSkillCommandsTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.project = Path(holder.name).resolve() / "project with spaces"
        self.native = ".codex/skills/acr__jbaruch__coding-policy__release"
        self.skill = self.project / self.native
        self.skill.mkdir(parents=True)
        # A command target must exist but must never run during selector checks.
        (self.skill / "release.sh").write_text("exit 91\n")
        self.markdown = self.skill / "SKILL.md"

    def write_command(self, selected, target="release.sh", interpreter="bash"):
        self.markdown.write_text('```bash\nKS="' + selected + '"; [ -d "$KS" ] || exit 1\n'
                                 + interpreter + ' "$KS/' + target + '"\n```\n')

    def verify(self):
        return CHECK.verify_skill_commands(self.project, ".codex", "coding-policy", "KS", ("release",), CHECK.runtime_environment())

    def test_native_root_with_spaces_resolves_without_running_the_business_command(self):
        self.write_command(self.native + "/")
        self.assertEqual(self.verify(), {"release": 1})

    def test_isolated_python_target_is_verified_without_running_it(self):
        (self.skill / "prepare-briefs.py").write_text("raise SystemExit(91)\n")
        self.write_command(self.native + "/", "prepare-briefs.py", "python3 -I")
        self.assertEqual(self.verify(), {"release": 1})

    def test_isolated_python_keeps_owned_target_and_interpreter_checks(self):
        (self.skill.parent / "outside.py").write_text("raise SystemExit(92)\n")
        for target in ("missing.py", "../outside.py", "release.sh"):
            with self.subTest(target=target):
                self.write_command(self.native + "/", target, "python3 -I")
                with self.assertRaises(CHECK.BehaviorFailure):
                    self.verify()

    def test_unrecognized_interpreter_flags_still_fail(self):
        for interpreter in ("bash -I", "python3 -c", "python3 -I -c"):
            with self.subTest(interpreter=interpreter):
                self.write_command(self.native + "/", interpreter=interpreter)
                with self.assertRaises(CHECK.BehaviorFailure):
                    self.verify()

    def test_commands_can_select_another_owned_skill_in_the_same_package(self):
        other = self.skill.with_name("acr__jbaruch__coding-policy__onboard-repo")
        other.mkdir()
        (other / "onboard.sh").write_text("exit 93\n")
        self.write_command(self.native + "/")
        (other / "SKILL.md").write_text(self.markdown.read_text())
        self.write_command(str(other.relative_to(self.project)) + "/", "onboard.sh")
        result = CHECK.verify_skill_commands(self.project, ".codex", "coding-policy", "KS",
                                             ("release", "onboard-repo"), CHECK.runtime_environment())
        self.assertEqual(result, {"release": 1, "onboard-repo": 1})

    def test_unconverted_tessl_root_and_existing_foreign_root_fail(self):
        for selected in (".tessl/plugins/jbaruch/coding-policy/skills/release/", "other-installation/"):
            with self.subTest(selected=selected):
                if selected == "other-installation/":
                    (self.project / selected).mkdir()
                self.write_command(selected)
                with self.assertRaises(CHECK.BehaviorFailure):
                    self.verify()

    def test_missing_target_and_target_outside_owned_skill_fail(self):
        (self.skill.parent / "outside.sh").write_text("exit 92\n")
        for target in ("missing.sh", "../outside.sh"):
            with self.subTest(target=target):
                self.write_command(self.native + "/", target)
                with self.assertRaises(CHECK.BehaviorFailure):
                    self.verify()

    def test_missing_selector_and_empty_coverage_fail(self):
        for content in ('```bash\nbash "$KS/release.sh"\n```\n', "No commands\n"):
            with self.subTest(content=content):
                self.markdown.write_text(content)
                with self.assertRaises(CHECK.BehaviorFailure):
                    self.verify()


if __name__ == "__main__":
    unittest.main()
