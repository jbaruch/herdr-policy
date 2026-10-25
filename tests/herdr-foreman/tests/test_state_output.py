"""Whole-state inspection must not put growing owner history into stdout."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import io
import json
import tempfile
import unittest
from unittest.mock import patch

from foreman import cli, context_output
from foreman.errors import UsageError
from foreman.state import add_assignment, empty_state, save_state

AT = "2026-02-03T10:00:00+00:00"


class StateOutputTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state = self.root / "state.json"

    def invoke(self, *command):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(cli, "_client", side_effect=AssertionError("Inspection must not contact Herdr")):
            code = cli.main([*command, "--state", str(self.state), "--config", str(self.root / "absent.json")],
                            stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def seed(self, count):
        state = empty_state()
        for index in range(count):
            add_assignment(state, AT, "developer", "worker", task="task-{}".format(index))
        save_state(self.state, state)
        return self.state.read_bytes()

    def test_small_state_and_status_keep_their_document_shapes(self):
        before = self.seed(1)
        code, out, err = self.invoke("state")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out), json.loads(before))
        code, out, err = self.invoke("status")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(set(json.loads(out)), {"schema_version", "tasks"})
        self.assertEqual(set(json.loads(out)["tasks"]), {"task-0"})
        self.assertEqual(self.state.read_bytes(), before)

    def test_large_state_and_status_refuse_without_partial_stdout_or_owner_edits(self):
        before = self.seed(150)
        for command in ("state", "status"):
            with self.subTest(command=command):
                code, out, err = self.invoke(command)
                self.assertEqual((code, out), (1, ""))
                diagnostic = json.loads(err)
                self.assertEqual(diagnostic["details"]["reason"], "context_budget_exceeded")
                self.assertFalse(diagnostic["details"]["context_complete"])
                self.assertIn("status --task", diagnostic["message"])
                self.assertEqual(self.state.read_bytes(), before)

    def test_selected_status_stays_small_and_matches_unfiltered_status(self):
        self.seed(1)
        _, original, _ = self.invoke("status")
        before = self.seed(150)
        code, out, err = self.invoke("status", "--task", "task-0")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out), json.loads(original))
        self.assertLessEqual(len(out.encode()), context_output.OUTPUT_BYTES)
        self.assertEqual(self.state.read_bytes(), before)

    def test_unknown_or_oversized_selection_cannot_look_like_an_empty_success(self):
        before = self.seed(1)
        for task in ("missing-task", "x" * 1_025):
            with self.subTest(task_bytes=len(task)):
                code, out, err = self.invoke("status", "--task", task)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("canonical", json.loads(err)["message"])
                self.assertLess(len(err.encode()), context_output.OUTPUT_BYTES)
                self.assertEqual(self.state.read_bytes(), before)

    def test_budget_includes_json_escaping_and_final_newline(self):
        # UTF-8 content alone fits, but its JSON escape expansion does not.
        document = {"value": "\U0001f603" * 2_000}
        self.assertLess(len(document["value"].encode()), context_output.OUTPUT_BYTES)
        with self.assertRaises(UsageError):
            context_output.enforce_budget(document, "Select a narrower question.")
        # An exact boundary succeeds; one extra printed byte must refuse.
        overhead = len((json.dumps({"value": ""}, indent=2) + "\n").encode())
        document = {"value": "x" * (context_output.OUTPUT_BYTES - overhead)}
        self.assertIs(context_output.enforce_budget(document, "Narrow the question."), document)
        document["value"] += "x"
        with self.assertRaises(UsageError):
            context_output.enforce_budget(document, "Narrow the question.")


if __name__ == "__main__":
    unittest.main()
