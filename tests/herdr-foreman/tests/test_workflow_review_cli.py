"""Exercise the shipped review reader's stdout, bounded reads and failures."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[3] / "skills/herdr-foreman/workflow-review.py"


class WorkflowReviewCliTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.path = Path(self.scratch.name) / "snapshot.json"
        self.snapshot = {"pr_number": 123, "head_sha": "a" * 40,
            "review_bodies": [{"id": 1, "body": "Full policy body."}, {"id": 2, "body": "Full advisory body."}],
            "inline_comment_bodies": [{"id": 3, "body": "Full inline body."}]}

    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, arguments)], capture_output=True,
            text=True, check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=10)

    def test_success_returns_one_identity_and_changed_bodies_change_it(self):
        self.path.write_text(json.dumps(self.snapshot))
        original = self.path.read_bytes()
        result = self.run_cli(self.path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        value = json.loads(result.stdout)
        self.assertEqual((value["schema_version"], value["pr_number"], value["head_sha"]), (1, 123, "a" * 40))
        self.assertEqual((value["reviews"], value["inline_comments"]), (2, 1))
        self.assertEqual(self.path.read_bytes(), original)
        self.snapshot["review_bodies"][0]["body"] = "A changed complete body."
        self.path.write_text(json.dumps(self.snapshot))
        changed = self.run_cli(self.path)
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertNotEqual(value["sha256"], json.loads(changed.stdout)["sha256"])

    def test_missing_unreadable_malformed_unsupported_and_oversized_inputs_fail(self):
        for body in (None, b"{", b"\xff", b"[]", b'{}', b" " * 2_097_153):
            with self.subTest(body=None if body is None else len(body)):
                if self.path.exists():
                    self.path.unlink()
                if body is not None:
                    self.path.write_bytes(body)
                result = self.run_cli(self.path)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("workflow-review:", result.stderr)
                self.assertIn("Restore the complete current canonical snapshot", result.stderr)
        self.path.unlink()
        self.path.mkdir()
        result = self.run_cli(self.path)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_invalid_arguments_fail_without_an_identity(self):
        for arguments in ((), ("--unknown",)):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
