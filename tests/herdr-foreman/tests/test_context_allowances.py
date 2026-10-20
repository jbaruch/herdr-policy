"""Mixed context APIs share exposure limits without changing task authority."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from contextlib import redirect_stderr
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from foreman import cli, context_output, cost_report, decision_budget, recovery, supervision
from foreman.errors import UsageError
from foreman.state import empty_state, save_state


AT = "2026-09-23T08:00:00+00:00"
REFERENCE = "https://github.com/fixture/project/issues/7"


class ContextAllowancesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "owner.json"
        environment = patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root / "state"),
                                             "XDG_CONFIG_HOME": str(self.root / "config")}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.state = empty_state()
        self.register(self.state, "one")
        save_state(self.path, self.state)
        supervision.bind(self.path,
            supervision.identity("fixture-context-session", str(self.root), "private-fixture", pane_id="fixture-pane"),
            AT, root=self.root / "bindings")
        hold = self.root / "hold.md"
        hold.write_text("Private fixture operator hold; preserve it.")
        supervision.hold(self.path, {"id": "hold", "kind": "waiting_for_user",
            "resume_condition": "Explicit fixture resume", "evidence": [str(hold)], "dispositions": []}, AT)

    def register(self, state, name):
        recovery.register_task(state["recovery"], {"task": name, "base_revision": "a" * 40,
            "scope": "Inspect bounded fixture evidence", "allowed_paths": ["*"],
            "authorization": {"source": "fixture operator request", "quote": "Inspect the task"}}, AT)

    def call(self, command, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stderr(err):
            code = cli.main([command, "--state", str(self.path), *arguments], stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def owners(self):
        return self.path.read_bytes(), supervision.store_path(self.path).read_bytes()

    def counter(self):
        return json.loads(decision_budget.location(self.path).read_text())

    def test_result_schemas_and_owner_holds_survive_exact_cross_api_charging(self):
        original = self.owners()
        printed = 0
        for command, arguments in (("state", ()), ("status", ("--task", "one")),
                                   ("cost-report", ("--task", "one", "--limit", "1")),
                                   ("memory-list", ("--now", AT))):
            with self.subTest(command=command):
                code, out, err = self.call(command, *arguments)
                self.assertEqual(code, 0, err)
                self.assertLessEqual(len((out + err).encode()), context_output.OUTPUT_BYTES)
                result = json.loads(out)
                if command == "state":
                    self.assertEqual(result, json.loads(original[0]))
                if command == "cost-report":
                    self.assertEqual(result["coverage"]["returned"], 1)
                    self.assertEqual(result["tasks"][0]["tokens"]["output"], "unknown")
                printed += len((out + err).encode())
                self.assertEqual(self.counter()["returned_bytes"], printed)
                self.assertEqual(self.counter()["tasks"], {})
                self.assertEqual(self.owners(), original)
        self.assertIsNone(supervision.load(self.path)["holds"][0]["resumed_at"])
        self.assertNotIn("Private fixture", decision_budget.location(self.path).read_text())

    def test_mixed_api_exhaustion_refuses_before_output_and_refunds_nothing(self):
        self.assertEqual(self.call("status")[0], 0)
        used = self.counter()["returned_bytes"]
        counter_before = decision_budget.location(self.path).read_bytes()
        original = self.owners()
        source = {"id": 100, "url": REFERENCE, "body": "Current evidence", "body_available": True, "updated_at": AT}
        reply = subprocess.CompletedProcess([], 0, ("HTTP/2.0 200 OK\n\n" + json.dumps(source)).encode())
        with patch.object(decision_budget, "FOREMAN_BYTES", used + 25), \
                patch("foreman.github_context.subprocess.run", return_value=reply):
            for command, arguments in (("memory-list", ("--now", AT)),
                                       ("cost-report", ("--task", "one", "--limit", "1")),
                                       ("github-context", ("--reference", REFERENCE, "--question", "What changed?")),
                                       ("load-set", ("--decision", "brief", "--task", "one"))):
                with self.subTest(command=command):
                    code, out, err = self.call(command, *arguments)
                    self.assertEqual((code, out), (1, ""), err)
                    self.assertEqual(json.loads(err)["details"]["reason"], "decision_context_budget_exceeded")
                    self.assertEqual(decision_budget.location(self.path).read_bytes(), counter_before)
                    self.assertEqual(self.owners(), original)

    def test_load_set_and_other_views_use_the_same_existing_counter(self):
        code, out, err = self.call("load-set", "--decision", "brief", "--task", "one")
        self.assertEqual(code, 0, err)
        before = self.counter()["returned_bytes"]
        task_before = self.counter()["tasks"]["one"]
        code, out, err = self.call("status", "--task", "one")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.counter()["returned_bytes"], before + len((out + err).encode()))
        self.assertEqual(self.counter()["tasks"]["one"], task_before)

    def test_unavailable_counter_withholds_results_and_original_error_data(self):
        self.assertEqual(self.call("status")[0], 0)
        counter = decision_budget.location(self.path)
        original = self.owners()
        private = "PRIVATE-FIXTURE-ERROR-DATA"

        def private_error(*args, **options):
            raise UsageError(private, {})

        for missing in (False, True):
            if missing:
                counter.unlink()
            else:
                counter.write_text("unsupported fixture counter")
            before = counter.read_bytes() if counter.exists() else None
            for handler in (cli.cmd_status, private_error):
                with self.subTest(missing=missing, handler=handler.__name__), \
                        patch.dict(cli.COMMANDS, {"status": handler}):
                    code, out, err = self.call("status", "--task", "one")
                    self.assertEqual((code, out), (1, ""))
                    self.assertNotIn(private, err)
                    self.assertLessEqual(len(err.encode()), context_output.OUTPUT_BYTES)
                    self.assertIn("context", json.loads(err)["message"].lower())
                    self.assertEqual(counter.read_bytes() if counter.exists() else None, before)
                    self.assertEqual(self.owners(), original)

    def test_corrupt_private_schema_is_refused_without_empty_success_or_leakage(self):
        private = "PRIVATE-FIXTURE-SCHEMA-DATA"
        self.path.write_text(json.dumps({"schema_version": private * 4000}))
        original = self.path.read_bytes()
        printed = 0
        for command in ("state", "status", "cost-report"):
            with self.subTest(command=command):
                code, out, err = self.call(command)
                self.assertEqual((code, out), (1, ""))
                self.assertNotIn(private, err)
                self.assertLessEqual(len(err.encode()), context_output.OUTPUT_BYTES)
                self.assertEqual(self.path.read_bytes(), original)
                printed += len(err.encode())
                self.assertEqual(self.counter()["returned_bytes"], printed)

    def test_oversized_error_or_warning_is_replaced_by_a_complete_bounded_failure(self):
        private = "Private fixture diagnostic body"
        printed = 0

        def large_error(*args, **options):
            raise UsageError(private * 4000, {})

        def large_warning(args, client=None, warn=None, trace=None):
            assert warn is not None
            warn(private * 4000)
            self.fail("An overflowing diagnostic cannot reach a success payload")

        for handler in (large_error, large_warning):
            with self.subTest(handler=handler.__name__), patch.dict(cli.COMMANDS, {"status": handler}):
                code, out, err = self.call("status")
                self.assertEqual((code, out), (1, ""))
                self.assertNotIn(private, err)
                self.assertFalse(json.loads(err)["details"]["context_complete"])
                self.assertLessEqual(len(err.encode()), context_output.OUTPUT_BYTES)
                printed += len(err.encode())
                self.assertEqual(self.counter()["returned_bytes"], printed)

    def test_cost_pages_cover_many_tasks_without_inventing_measured_tokens(self):
        state = empty_state()
        names = ["task-{:03}".format(n) for n in range(120)]
        for name in names:
            self.register(state, name)
        offset, seen = 0, []
        for _ in range(120):
            result = cost_report.view(state, limit=50, offset=offset)
            self.assertLessEqual(len(context_output.printed_json(result).encode()), context_output.OUTPUT_BYTES)
            self.assertEqual(result["coverage"]["total"], len(names))
            self.assertFalse(result["authorizes_progression"])
            self.assertEqual(result["unrecorded"], list(cost_report.UNRECORDED))
            seen.extend(row["task"] for row in result["tasks"])
            for row in result["tasks"]:
                self.assertTrue(all(value == "unknown" for value in row["tokens"].values()))
            next_offset = result["coverage"]["next_offset"]
            if next_offset is None:
                break
            self.assertGreater(next_offset, offset)
            offset = next_offset
        else:
            self.fail("Finite task cost pages did not finish")
        self.assertEqual(seen, names)

    def test_selected_cost_record_cannot_be_skipped_with_collection_offset(self):
        original = self.owners()
        for offset in (1, 999):
            with self.subTest(offset=offset):
                code, out, err = self.call("cost-report", "--task", "one", "--offset", str(offset))
                self.assertEqual((code, out), (1, ""))
                self.assertIn("Omit --offset", json.loads(err)["message"])
                self.assertEqual(self.owners(), original)
        code, out, err = self.call("cost-report", "--task", "one")
        self.assertEqual(code, 0, err)
        self.assertEqual([row["task"] for row in json.loads(out)["tasks"]], ["one"])

    def test_malformed_task_argv_refuses_without_traceback_or_owner_change(self):
        original = self.owners()
        for command in ("cost-report", "status"):
            with self.subTest(command=command):
                code, out, err = self.call(command, "--task", "\udcff")
                self.assertEqual((code, out), (1, ""))
                self.assertIn("valid UTF-8", json.loads(err)["message"])
                self.assertNotIn("Traceback", err)
                self.assertNotIn("\\udcff", err)
                self.assertEqual(self.owners(), original)

    def test_cost_page_fitting_calculates_each_selected_task_at_most_once(self):
        state = empty_state()
        for index in range(50):
            self.register(state, "task-{:03}".format(index))
        with patch.object(cost_report, "_task_report", wraps=cost_report._task_report) as calculate:
            result = cost_report.view(state, limit=50)
        self.assertLess(result["coverage"]["returned"], 50)
        self.assertLessEqual(calculate.call_count, 50)
        self.assertEqual(len({call.args[0] for call in calculate.call_args_list}), calculate.call_count)

    def test_oversized_parse_error_keeps_exit_two_without_echoing_argument_data(self):
        private = "Private fixture argument body"
        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
            cli.main(["github-context", "--reference", REFERENCE, "--question", "What changed?",
                      "--section", private * 4000])
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn(private, error.getvalue())
        self.assertLessEqual(len(error.getvalue().encode()), context_output.OUTPUT_BYTES)


if __name__ == "__main__":
    unittest.main()
