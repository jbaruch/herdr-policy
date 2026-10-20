"""Installation conformance keeps setup failures distinct from failed behavior."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installation_check", ROOT / "scripts/check-installations.py")
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class InstallationErrorsTest(unittest.TestCase):
    def test_installed_readiness_requires_bounded_readonly_owner_observation(self):
        valid = {"schema_version": 2, "counts_scope": "returned_items", "items": [],
                 "pagination": {"total": 0}, "counts": {"dispatchable": 0},
                 "authorizes_dispatch": False, "authorizes_progression": False}
        with tempfile.TemporaryDirectory() as scratch:
            project = Path(scratch)
            with patch.object(CHECK, "command", return_value=json.dumps(valid)):
                CHECK.verify_workflow_readiness(project, project / "skill", {})
            for change in ({"authorizes_dispatch": True}, {"items": [{"task": "foreign"}]},
                           {"padding": "x" * 16_384}, {"counts_scope": "all_tasks"}):
                with self.subTest(change=next(iter(change))):
                    with patch.object(CHECK, "command", return_value=json.dumps({**valid, **change})):
                        with self.assertRaises(CHECK.BehaviorFailure):
                            CHECK.verify_workflow_readiness(project, project / "skill", {})
            (project / "readiness-owner.json").write_text("Unexpected owner write")
            with patch.object(CHECK, "command", return_value=json.dumps(valid)):
                with self.assertRaises(CHECK.BehaviorFailure):
                    CHECK.verify_workflow_readiness(project, project / "skill", {})

    def test_credentials_are_scoped_to_registry_install_not_candidate_execution(self):
        secret = "private fixture value"
        with patch.dict(os.environ, {"GH_TOKEN": secret, "TESSL_TOKEN": secret, "PATH": "/fixture/bin"}, clear=True):
            result = subprocess.CompletedProcess([], 0, stdout='{"ok":true}', stderr="")
            with patch.object(CHECK.subprocess, "run", return_value=result) as run:
                CHECK.acr("install", Path("/unused"), "fixture:source")
                self.assertEqual(run.call_args.kwargs["env"], {"PATH": "/fixture/bin", "GH_TOKEN": secret})
                CHECK.acr("realize", Path("/unused"))
                self.assertEqual(run.call_args.kwargs["env"], {"PATH": "/fixture/bin"})
                CHECK.command("bash", "fixture-hook", env=dict(os.environ), check_behavior=True)
                self.assertEqual(run.call_args.kwargs["env"], {"PATH": "/fixture/bin"})

    def test_candidate_output_is_not_copied_into_failure_diagnostics(self):
        secret = "private fixture value"
        for code in (0, 7):
            with self.subTest(code=code):
                result = subprocess.CompletedProcess([], code, stdout=secret, stderr=secret)
                with patch.object(CHECK.subprocess, "run", return_value=result), self.assertRaises(CHECK.BehaviorFailure) as error:
                    CHECK.command("bash", "fixture-hook", check_behavior=True, quiet=True)
                self.assertNotIn(secret, str(error.exception))

    def test_real_candidate_process_does_not_receive_parent_credentials(self):
        with patch.dict(os.environ, {"GH_TOKEN": "private fixture value", "TESSL_TOKEN": "private fixture value"}):
            output = CHECK.command(sys.executable, "-c", "import os; print('GH_TOKEN' in os.environ or 'TESSL_TOKEN' in os.environ)",
                                   check_behavior=True)
        self.assertEqual(output, "False\n")

    def test_runtime_inventory_keeps_decoder_and_refuses_development_calibration(self):
        with tempfile.TemporaryDirectory() as scratch:
            skill = Path(scratch)
            with self.assertRaises(CHECK.BehaviorFailure):
                CHECK.verify_runtime_payload(skill)
            (skill / "foreman").mkdir()
            (skill / "foreman/remote_owner.py").write_text("")
            with self.assertRaises(CHECK.BehaviorFailure):
                CHECK.verify_runtime_payload(skill)
            (skill / "classify").mkdir()
            (skill / "classify/extract-answer.py").write_text("runtime envelope decoder")
            for name in ("foreman/coordination_metrics.py", "measurements.py", "references/coordination-metrics.md"):
                path = skill / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("packaged measurement runtime fixture")
            CHECK.verify_runtime_payload(skill)
            for name in ("adversarial.py", "evaluate.sh", "scoring.py"):
                path = skill / "classify" / name
                path.write_text("development calibration fixture")
                with self.subTest(name=name), self.assertRaises(CHECK.BehaviorFailure):
                    CHECK.verify_runtime_payload(skill)
                path.unlink()
            CHECK.verify_runtime_payload(skill)
            (skill / "tests").mkdir()
            with self.assertRaises(CHECK.BehaviorFailure):
                CHECK.verify_runtime_payload(skill)

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

    def test_zero_exit_hook_fallback_is_not_successful_owner_execution(self):
        for output, diagnostic in (('{"decision":"block"}', ""), ("", "restore the hook")):
            with self.subTest(output=output, diagnostic=diagnostic):
                result = subprocess.CompletedProcess([], 0, stdout=output, stderr=diagnostic)
                with patch.object(CHECK.subprocess, "run", return_value=result):
                    with self.assertRaises(CHECK.BehaviorFailure):
                        CHECK.command("bash", "fixture-hook", check_behavior=True, quiet=True)
        result = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.object(CHECK.subprocess, "run", return_value=result):
            self.assertEqual(CHECK.command("bash", "fixture-hook", check_behavior=True, quiet=True), "")


if __name__ == "__main__":
    unittest.main()
