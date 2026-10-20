"""The hook selects installed owners and skips standalone prerequisites."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills/herdr-foreman/native-hook.sh"
SKILL = "acr__jbaruch__herdr-policy__herdr-foreman"
EVENTS = {"reset-input": "reset_input_hook", "supervision-stop": "supervision_hook",
          "session-start": "session_start_hook"}


class HerdrHookTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.project = Path(holder.name).resolve() / "project with spaces\n"
        self.project.mkdir()
        self.foreign = Path(holder.name).resolve() / "foreign"
        self.foreign.mkdir()
        self.env = dict(os.environ)
        self.env.pop("HERDR_ENV", None)
        self.env.pop("HERDR_PANE_ID", None)

    def install(self, host=None):
        if host is None:
            package = self.project / ".tessl/plugins/jbaruch/herdr-policy"
            hook = package / "skills/herdr-foreman/native-hook.sh"
            skill = package / "skills/herdr-foreman"
        else:
            hook = self.project / host / "hooks/acr__jbaruch__herdr-policy__herdr-reset-input/native-hook.sh"
            skill = self.project / host / "skills" / SKILL
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(SOURCE.read_text())
        (skill / "foreman").mkdir(parents=True)
        (skill / "foreman/__init__.py").write_text("")
        for module in EVENTS.values():
            (skill / "foreman" / (module + ".py")).write_text(
                "import json,os,sys\n"
                "print(json.dumps({'owner':'installed','module':" + repr(module) +
                ",'input':sys.stdin.read(),'cwd':os.getcwd(),'adapter':os.environ.get('HERDR_HOOK_ADAPTER')}))\n")
        return hook

    def run_hook(self, hook, event, *, relative=False, **extra):
        env = {**self.env, **extra}
        cwd = self.project if relative else self.foreign
        command = str(hook.relative_to(cwd)) if relative else str(hook)
        return subprocess.run(["/bin/bash", command, event], cwd=cwd, env=env,
                              input='{"session_id":"fixture"}\n', capture_output=True, text=True)

    def test_standalone_skips_missing_runtime_and_python(self):
        hook = self.foreign / "native-hook.sh"
        hook.write_text(SOURCE.read_text())
        for event in EVENTS:
            with self.subTest(event=event):
                result = self.run_hook(hook, event, PATH=str(self.foreign / "no-tools"))
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_tessl_and_relative_launch_forward_input_to_installed_owner(self):
        hook = self.install()
        for event in EVENTS:
            for relative in (False, True):
                with self.subTest(event=event, relative=relative):
                    result = self.run_hook(hook, event, relative=relative, HERDR_ENV="fixture")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)["owner"], "installed")
                    self.assertEqual(json.loads(result.stdout)["module"], EVENTS[event])
                    self.assertEqual(json.loads(result.stdout)["input"], '{"session_id":"fixture"}\n')
                    self.assertEqual(json.loads(result.stdout)["cwd"],
                                     str(self.project if relative else self.foreign))

    def test_acr_hook_copy_uses_its_own_project_instead_of_the_cwd(self):
        for host in (".codex", ".claude", ".cursor"):
            with self.subTest(host=host):
                hook = self.install(host)
                for event in EVENTS:
                    result = self.run_hook(hook, event, HERDR_ENV="fixture")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)["owner"], "installed")
                    self.assertEqual(json.loads(result.stdout)["module"], EVENTS[event])
                    self.assertEqual(json.loads(result.stdout)["cwd"], str(self.foreign))
                    self.assertEqual(json.loads(result.stdout)["adapter"], {".codex": "codex", ".claude": "claude-code", ".cursor": "cursor"}[host])

    def test_missing_native_sibling_does_not_select_another_host_or_tessl_owner(self):
        self.install()
        self.install(".claude")
        hook = self.project / ".codex/hooks/acr__jbaruch__herdr-policy__herdr-reset-input/native-hook.sh"
        hook.parent.mkdir(parents=True)
        hook.write_text(SOURCE.read_text())
        result = self.run_hook(hook, "reset-input", HERDR_ENV="fixture")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["decision"], "block")
        self.assertIn("Restore", json.loads(result.stdout)["reason"])

    def test_checkout_and_inherited_pythonpath_cannot_replace_the_owner(self):
        hook = self.install()
        (self.foreign / "foreman").mkdir()
        (self.foreign / "foreman/__init__.py").write_text("raise RuntimeError('wrong owner')\n")
        result = self.run_hook(hook, "supervision-stop", HERDR_ENV="fixture", PYTHONPATH=str(self.foreign), CDPATH=str(self.foreign))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["owner"], "installed")

    def test_empty_but_set_team_environment_reaches_the_identity_checker(self):
        result = self.run_hook(self.install(), "reset-input", HERDR_ENV="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["owner"], "installed")

    def test_team_prerequisite_failure_retains_the_event_failure_contract(self):
        hook = self.install()
        reset = self.run_hook(hook, "reset-input", HERDR_ENV="fixture", PATH=str(self.foreign / "no-tools"))
        self.assertEqual(reset.returncode, 0)
        self.assertEqual(json.loads(reset.stdout)["decision"], "block")
        stop = self.run_hook(hook, "supervision-stop", HERDR_ENV="fixture", PATH=str(self.foreign / "no-tools"))
        self.assertEqual((stop.returncode, stop.stdout), (0, ""))
        self.assertIn("restore", stop.stderr)

    def test_unknown_event_is_a_usage_error(self):
        result = self.run_hook(self.install(), "other")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn("usage", result.stderr)


if __name__ == "__main__":
    unittest.main()
