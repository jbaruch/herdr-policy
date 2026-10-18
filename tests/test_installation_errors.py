"""Installation conformance keeps setup failures distinct from failed behavior."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installation_check", ROOT / "scripts/check-installations.py")
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class InstallationErrorsTest(unittest.TestCase):
    def test_failed_source_install_is_setup_but_failed_realization_is_behavior(self):
        failure = subprocess.CompletedProcess([], 7, stdout="", stderr="fixture rejection")
        with patch.object(CHECK.subprocess, "run", return_value=failure):
            with self.assertRaises(OSError):
                CHECK.acr("install", Path("/unused"), "fixture:source")
            with self.assertRaises(CHECK.BehaviorFailure):
                CHECK.acr("realize", Path("/unused"))

    def test_installed_hook_failure_is_behavior_and_missing_executable_is_setup(self):
        failure = subprocess.CompletedProcess([], 7, stdout="", stderr="fixture rejection")
        with patch.object(CHECK.subprocess, "run", return_value=failure):
            with self.assertRaises(CHECK.BehaviorFailure):
                CHECK.command("bash", "fixture-hook", check_behavior=True)
        with patch.object(CHECK.subprocess, "run", side_effect=FileNotFoundError("missing executable")):
            with self.assertRaises(OSError):
                CHECK.command("acr", "check", check_behavior=True)

    def test_cli_preserves_the_distinct_failure_verdicts(self):
        arguments = ["check-installations.py", "--herdr-source", "github:jbaruch/herdr-policy@" + "1" * 40]
        for exception, expected in ((CHECK.BehaviorFailure("hook refused"), 1), (OSError("CLI unavailable"), 2)):
            with self.subTest(expected=expected):
                output, errors = io.StringIO(), io.StringIO()
                with patch.object(sys, "argv", arguments), patch.object(CHECK, "exercise", side_effect=exception), redirect_stdout(output), redirect_stderr(errors):
                    result = CHECK.main()
                self.assertEqual(result, expected)
                self.assertFalse(json.loads(output.getvalue())["passed"])
                self.assertIn(str(exception), errors.getvalue())


if __name__ == "__main__":
    unittest.main()
