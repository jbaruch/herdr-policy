"""Public resolver outcomes for installed policy artifacts; no user HOME edits."""

import sys as _test_sys
from pathlib import Path as _TestPath
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import json
import os
import shutil
from foreman.policy_paths import RELEASE_FILES
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = (Path(__file__).resolve().parents[3] / "skills/herdr-foreman") / "resolve-policy-paths.sh"
RELEASE = Path("plugins/jbaruch/coding-policy/skills/release/SKILL.md")
TEAM = Path("references/worker-context.md")


class ResolvePolicyPaths(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project with spaces"
        self.project.mkdir()
        self.local = self.project / ".tessl"
        self.global_root = self.root / "global with spaces"
        self.skill = self.root / "herdr-policy/skills/herdr-foreman"
        (self.skill / "foreman").mkdir(parents=True)
        for filename in ("foreman/__init__.py", "foreman/errors.py", "foreman/policy_paths.py",
                         "policy-paths.py", "resolve-policy-paths.sh"):
            shutil.copyfile(SCRIPT.parent / filename, self.skill / filename)
        self.team = self.artifact(self.skill, TEAM)

    def artifact(self, root, relative, content="policy fixture\n"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        if relative == RELEASE:
            for name in RELEASE_FILES:
                helper = path.parent / name
                helper.parent.mkdir(parents=True, exist_ok=True)
                helper.write_text("fixture\n")
        return str(path)

    def invoke(self, *args, env=None):
        environment = dict(os.environ) if env is None else dict(env)
        environment.pop("HERDR_CODING_POLICY_ROOT", None)
        return subprocess.run(
            ["/bin/bash", str(self.skill / "resolve-policy-paths.sh"), *(args or (str(self.project), str(self.global_root)))],
            text=True, capture_output=True, check=False, env=environment,
        )

    def test_local_precedes_global_and_spaces_survive(self):
        expected = {"POLICY_INDEX": self.artifact(self.local, Path("RULES.md")),
                    "RELEASE_SKILL": self.artifact(self.local, RELEASE),
                    "TEAM_OPERATION": self.team}
        self.artifact(self.global_root, Path("RULES.md"))
        self.artifact(self.global_root, RELEASE)
        self.team
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)

    def test_global_only_install(self):
        expected = {"POLICY_INDEX": self.artifact(self.global_root, Path("RULES.md")),
                    "RELEASE_SKILL": self.artifact(self.global_root, RELEASE),
                    "TEAM_OPERATION": self.team}
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)

    def test_each_artifact_selects_its_own_available_root(self):
        expected = {"POLICY_INDEX": self.artifact(self.local, Path("RULES.md")),
                    "RELEASE_SKILL": self.artifact(self.global_root, RELEASE),
                    "TEAM_OPERATION": self.team}
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)

    def test_missing_release_emits_no_partial_result(self):
        self.artifact(self.local, Path("RULES.md"))
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("install", result.stderr)
        self.assertIn("coding-policy", result.stderr)

    def test_missing_team_operation_emits_no_partial_result(self):
        self.artifact(self.local, Path("RULES.md"))
        self.artifact(self.global_root, RELEASE)
        Path(self.team).unlink()
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn(str(self.team), result.stderr)

    def test_empty_or_directory_artifacts_cannot_supply_policy(self):
        self.artifact(self.local, Path("RULES.md"), "")
        (self.local / RELEASE).mkdir(parents=True)
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_invalid_roots_are_actionable(self):
        for args in [("relative", str(self.global_root)),
                     (str(self.project), "relative"),
                     (str(self.root / "absent"), str(self.global_root)),
                     (str(self.project), str(self.global_root) + "\n")]:
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("absolute", result.stderr)

    def test_missing_python_is_a_precondition_failure(self):
        empty_bin = self.root / "empty-bin"
        empty_bin.mkdir()
        result = self.invoke(env={**os.environ, "PATH": str(empty_bin)})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("install Python", result.stderr)


if __name__ == "__main__":
    unittest.main()
