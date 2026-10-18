"""Development runners preserve verdicts, isolation, and machine-readable output."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DevelopmentToolsTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="herdr-development-tools-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        (self.root / "scripts").mkdir()
        for name in ("run-tests.py", "run-diagnostics.py"):
            shutil.copyfile(ROOT / "scripts" / name, self.root / "scripts" / name)
        self.bin = self.root / "bin"
        self.bin.mkdir()

    def suite(self, name, status=0):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".sh":
            path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n"
                            "main() { printf 'hook suite output\\n'; return " + str(status) + "; }\n"
                            'if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi\n')
        else:
            path.write_text("import json, os\nfrom pathlib import Path\n"
                            "def main():\n"
                            "    record = {key: os.environ.get(key) for key in "
                            "('XDG_STATE_HOME', 'XDG_CONFIG_HOME', 'HERDR_ENV', 'HERDR_PANE_ID', 'PYTHONPATH')}\n"
                            "    record['suite'] = " + repr(name) + "\n"
                            "    with Path(" + repr(str(self.root / "observations.jsonl")) + ").open('a') as target:\n"
                            "        target.write(json.dumps(record) + '\\n')\n"
                            "    print('python suite output')\n"
                            "    return " + str(status) + "\n"
                            "if __name__ == '__main__':\n    raise SystemExit(main())\n")
        return path

    def tool(self, name, status=0):
        path = self.bin / name
        path.write_text("#!" + sys.executable + "\n"
                        "def main():\n"
                        "    import sys\n"
                        "    print('fixture tool output')\n"
                        "    print('fixture tool diagnostic', file=sys.stderr)\n"
                        "    return " + str(status) + "\n"
                        "if __name__ == '__main__':\n    raise SystemExit(main())\n")
        path.chmod(0o700)

    def run_tool(self, name, *arguments, private_tools=False):
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        if private_tools:
            environment["PATH"] = str(self.bin)
        else:
            environment.update(HERDR_ENV="fixture-round", HERDR_PANE_ID="fixture-pane",
                               PYTHONPATH="fixture-python-path")
        result = subprocess.run([sys.executable, str(self.root / "scripts" / name), *arguments],
                                cwd=self.root, env=environment, capture_output=True, text=True)
        return result, json.loads(result.stdout)

    def observations(self):
        path = self.root / "observations.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_default_discovery_runs_runtime_and_hook_suites_in_private_environments(self):
        self.suite("tests/test_first.py")
        self.suite("tests/runtime/tests/test_second.py")
        self.suite("tests/hooks/test_third.sh")
        self.suite("tests/fixtures/test_ignored.py", status=1)
        result, payload = self.run_tool("run-tests.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((payload["suites"], payload["passed"], payload["failed"]), (3, 3, 0))
        records = self.observations()
        self.assertEqual({row["suite"] for row in records},
                         {"tests/test_first.py", "tests/runtime/tests/test_second.py"})
        self.assertEqual(len({row["XDG_STATE_HOME"] for row in records}), 2)
        self.assertEqual(len({row["XDG_CONFIG_HOME"] for row in records}), 2)
        for record in records:
            for key in ("HERDR_ENV", "HERDR_PANE_ID", "PYTHONPATH"):
                self.assertIsNone(record[key])
            for key in ("XDG_STATE_HOME", "XDG_CONFIG_HOME"):
                self.assertFalse(Path(record[key]).exists(), "private state must be cleaned up")
        self.assertIn("python suite output", result.stderr)
        self.assertIn("hook suite output", result.stderr)

    def test_explicit_selection_and_failed_suites_preserve_later_results(self):
        self.suite("tests/test_bad.py", status=7)
        self.suite("tests/test_good.py")
        result, payload = self.run_tool("run-tests.py", "tests/test_bad.py", "tests/test_good.py")
        self.assertEqual(result.returncode, 1)
        self.assertEqual((payload["suites"], payload["passed"], payload["failed"]), (2, 1, 1))
        self.assertEqual(payload["failures"], ["tests/test_bad.py"])
        self.assertEqual([row["suite"] for row in self.observations()],
                         ["tests/test_bad.py", "tests/test_good.py"])
        result, payload = self.run_tool("run-tests.py", "tests/test_good.py")
        self.assertEqual((result.returncode, payload["suites"], payload["failed"]), (0, 1, 0))

    def test_invalid_suite_paths_and_empty_discovery_fail_before_running_any_suite(self):
        result, payload = self.run_tool("run-tests.py")
        self.assertEqual((result.returncode, payload["suites"]), (2, 0))
        self.suite("tests/test_good.py")
        for invalid in ("tests/missing.py", "../outside.py", str(self.root / "tests/test_good.py"), "scripts"):
            with self.subTest(invalid=invalid):
                result, payload = self.run_tool("run-tests.py", "tests/test_good.py", invalid)
                self.assertEqual((result.returncode, payload["suites"]), (2, 0))
                self.assertIn("repair the development environment", result.stderr)
                self.assertEqual(self.observations(), [])

    def test_diagnostics_success_emits_one_json_result_with_tool_text_on_stderr(self):
        self.suite("tests/hooks/test_smoke.sh")
        self.tool("shellcheck")
        self.tool("pyright")
        result, payload = self.run_tool("run-diagnostics.py", private_tools=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tools"], {"shellcheck": 0, "pyright": 0})
        self.assertIn("fixture tool output", result.stderr)
        self.assertIn("fixture tool diagnostic", result.stderr)

    def test_each_diagnostic_failure_is_reported_without_skipping_the_other_tool(self):
        self.suite("tests/hooks/test_smoke.sh")
        for failed in ("shellcheck", "pyright"):
            with self.subTest(failed=failed):
                for name in ("shellcheck", "pyright"):
                    self.tool(name, status=int(name == failed))
                result, payload = self.run_tool("run-diagnostics.py", private_tools=True)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["tools"][failed], 1)
                self.assertEqual(len(payload["tools"]), 2)
                self.assertIn("fix the reported findings", result.stderr)

    def test_missing_diagnostic_tools_or_source_tree_are_setup_errors(self):
        for available, missing in ((None, "shellcheck"), ("shellcheck", "pyright")):
            with self.subTest(missing=missing):
                if available:
                    self.tool(available)
                result, payload = self.run_tool("run-diagnostics.py", private_tools=True)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(payload["ok"])
                self.assertIn("install " + missing, result.stderr)
        self.tool("pyright")
        result, payload = self.run_tool("run-diagnostics.py", private_tools=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("restore the source tree", result.stderr)
        self.assertEqual(payload["tools"], {})


if __name__ == "__main__":
    unittest.main()
