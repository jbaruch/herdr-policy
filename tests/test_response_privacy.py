"""Provider and Herdr failures preserve outcomes without relaying response text."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/herdr-foreman"
PRIVATE = "response payload fixture"


class ResponsePrivacyTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.directory = Path(holder.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.report = self.directory / "report.md"
        self.report.write_text("No blocking findings.\n")
        self.environment = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                            "HERDR_ENV": "1", "HERDR_PANE_ID": "w1:p1", "HERDR_WORKSPACE_ID": "w1",
                            "PRIVACY_FIXTURE_RESPONSE": PRIVATE,
                            "XDG_STATE_HOME": str(self.directory / "state"),
                            "XDG_CONFIG_HOME": str(self.directory / "config")}

    def executable(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
        path.chmod(0o700)
        return path

    def invoke(self, script, *arguments, expected):
        result = subprocess.run(["bash", str(script), *map(str, arguments)], env=self.environment,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn(PRIVATE, result.stdout)
        self.assertNotIn(PRIVATE, result.stderr)
        return result

    def test_lookup_errors_do_not_relay_response_body_or_error_code(self):
        self.environment["HERDR_BIN"] = str(self.executable("herdr", """
printf '{"error":{"code":"%s","message":"%s"}}\\n' "$PRIVACY_FIXTURE_RESPONSE" "$PRIVACY_FIXTURE_RESPONSE" >&2
exit 1
"""))
        for script, arguments in (("roster.sh", ()), ("label-workspaces.sh", ("lead",)),
                                  ("wait-report.sh", ("--once", "worker", self.directory / "absent-report"))):
            with self.subTest(script=script):
                result = self.invoke(SKILL / script, *arguments, expected=2)
                self.assertIn("response withheld", result.stderr)

    def test_rename_errors_preserve_failed_result_without_response_text(self):
        self.environment["HERDR_BIN"] = str(self.executable("herdr", """
case "$1 $2" in
  'workspace list') printf '%s\\n' '{"result":{"workspaces":[{"workspace_id":"w1","name":""}]}}' ;;
  'agent list') printf '%s\\n' '{"result":{"agents":[]}}' ;;
  *) printf '%s\\n' "$PRIVACY_FIXTURE_RESPONSE" >&2; exit 1 ;;
esac
"""))
        result = self.invoke(SKILL / "label-workspaces.sh", "lead", expected=3)
        self.assertEqual(json.loads(result.stdout)["lead"]["state"], "failed")
        self.assertIn("rename failed", result.stderr)

    def test_empty_success_response_is_a_tool_failure(self):
        self.environment["HERDR_BIN"] = str(self.executable("herdr", "exit 0\n"))
        for script, arguments in (("roster.sh", ()), ("label-workspaces.sh", ("lead",)),
                                  ("wait-report.sh", ("--once", "worker", self.directory / "absent-report"))):
            with self.subTest(script=script):
                result = self.invoke(SKILL / script, *arguments, expected=2)
                self.assertEqual(result.stdout, "")

    def test_codex_failure_streams_do_not_reach_single_or_batch_diagnostics(self):
        self.executable("codex", """
cat >/dev/null
printf '%s\\n' "$PRIVACY_FIXTURE_RESPONSE"
printf '%s\\n' "$PRIVACY_FIXTURE_RESPONSE" >&2
exit 7
""")
        self.invoke(SKILL / "classify/classify-report.sh", self.report, "--agent", "codex", expected=2)
        batch = self.invoke(SKILL / "classify/classify-reports.sh", "--agent", "codex", self.report, expected=0)
        self.assertEqual(len(json.loads(batch.stdout)["unannotated"]), 1)

    def test_claude_error_result_is_not_a_diagnostic(self):
        raw = self.directory / "raw.json"
        raw.write_text(json.dumps({"type": "result", "is_error": True, "result": PRIVATE, "subtype": PRIVATE}))
        result = subprocess.run([sys.executable, str(SKILL / "classify/extract-answer.py"), "claude", str(raw),
                                 str(self.directory / "answer.json")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(PRIVATE, result.stderr)
        self.assertIn("check provider availability", result.stderr)


if __name__ == "__main__":
    unittest.main()
