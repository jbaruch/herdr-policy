"""Bounded context reads stay available without counters or authority changes."""

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
import hashlib
from unittest.mock import patch

from foreman import cli, context_output, cost_report, recovery, report_gates, supervision
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

    def test_bounded_reads_preserve_owner_holds_without_creating_accounting(self):
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
                self.assertEqual(self.owners(), original)
        self.assertIsNone(supervision.load(self.path)["holds"][0]["resumed_at"])
        self.assertFalse(Path(str(self.path) + ".context.json").exists())
        self.assertFalse(Path(str(self.path) + ".context-presence.json").exists())

    def test_exhausted_or_corrupt_legacy_counter_cannot_block_current_reads(self):
        counter = Path(str(self.path) + ".context.json")
        counter.write_text('{"schema_version":1,"returned_bytes":262144}')
        receipt = Path(str(self.path) + ".context-presence.json")
        receipt.write_text("unreadable legacy receipt")
        legacy = (counter.read_bytes(), receipt.read_bytes())
        original = self.owners()
        source = {"id": 100, "url": REFERENCE, "body": "Current evidence", "body_available": True, "updated_at": AT}
        reply = subprocess.CompletedProcess([], 0, ("HTTP/2.0 200 OK\n\n" + json.dumps(source)).encode())
        with patch("foreman.github_context.subprocess.run", return_value=reply):
            for command, arguments in (("memory-list", ("--now", AT)),
                                       ("cost-report", ("--task", "one", "--limit", "1")),
                                       ("github-context", ("--reference", REFERENCE, "--question", "What changed?")),
                                       ("load-set", ("--decision", "brief", "--task", "one"))):
                with self.subTest(command=command):
                    code, out, err = self.call(command, *arguments)
                    self.assertEqual(code, 0, err)
                    self.assertLessEqual(len((out + err).encode()), context_output.OUTPUT_BYTES)
                    self.assertNotIn("aggregate_budget", json.loads(out))
                    self.assertEqual((counter.read_bytes(), receipt.read_bytes()), legacy)
                    self.assertEqual(self.owners(), original)

    def test_exhaustion_cannot_deadlock_completed_deliveries_or_accept_their_tasks(self):
        supervision.resume(self.path, AT, expected_holds=["hold"])
        counter = Path(str(self.path) + ".context.json")
        counter.write_text('{"schema_version":1,"returned_bytes":262144}')
        original_counter = counter.read_bytes()
        receipts = {}
        for index in range(12):
            name = "done-{:02}".format(index)
            self.register(self.state, name)
            report = self.root / (name + ".md")
            report.write_text("Delivered report; task assessment remains open.\nVERDICT: blocking\n")
            # Previously authenticated wait receipts; native authentication has its own suites.
            receipt = self.root / (name + "-wait.json")
            receipt.write_text(json.dumps({"exit": 0, "report": str(report), "agent": name}))
            receipts[name] = str(receipt)
            supervision.enroll(self.path, {"id": name, "agent": name, "task": name,
                "report": str(report), "pane_id": "pane-" + name, "native_session": None}, AT)
            def seed_events(data):
                supervision.append_event(data, AT, name, "report_observed", {"present": True})
                if index < 10:
                    supervision.append_event(data, AT, name, "visible_observed", {"sha256": "a" * 64})
            supervision.transaction(self.path, seed_events)
        save_state(self.path, self.state)
        report = self.root / "done-00.md"
        report_gates.record_verdict(self.path, str(report), hashlib.sha256(report.read_bytes()).hexdigest(), "done-00", AT)
        original_state = self.path.read_bytes()
        original_gates = report_gates.storage_path(self.path).read_bytes()
        request = self.root / "handled.json"

        code, out, err = self.call("supervision-status", "--compact", "--section", "active", "--now", AT)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["active_page"]["total"], 12)
        after = 0
        while supervision.pending(supervision.load(self.path)):
            code, out, err = self.call("supervision-drain", "--compact", "--limit", "2",
                                       "--after", str(after), "--through", "22", "--now", AT)
            self.assertEqual(code, 0, err)
            self.assertLessEqual(len((out + err).encode()), context_output.OUTPUT_BYTES)
            page = json.loads(out)
            events = page["events"]
            self.assertTrue(events)
            request.write_text(json.dumps({"through": page["through"], "outcomes": [
                {"event": event["id"], "outcome": "Delivery authenticated; report remains unassessed.",
                 "evidence": [receipts[event["member"]]]} for event in events]}))
            code, _, err = self.call("supervision-ack", "--compact", "--record", str(request), "--now", AT)
            self.assertEqual(code, 0, err)
            after = int(events[-1]["id"].removeprefix("event-"))
            if after == 2:
                self.assertEqual(len(supervision.pending(supervision.load(self.path))), 20)
                with self.assertRaisesRegex(UsageError, "pending observations"):
                    supervision.resolve(self.path, {"id": "done-01", "outcome": "Not yet handled",
                                                    "evidence": [receipts["done-01"]]}, AT)
        for name, receipt in receipts.items():
            request.write_text(json.dumps({"id": name, "outcome": "Delivery observed; report/task still unaccepted.",
                                           "evidence": [receipt]}))
            code, _, err = self.call("supervision-resolve", "--record", str(request), "--now", AT)
            self.assertEqual(code, 0, err)
        data = supervision.load(self.path)
        self.assertFalse(any(member["active"] for member in data["members"]))
        self.assertEqual(supervision.pending(data), [])
        self.assertEqual(data["holds"][0]["resumed_at"], AT)
        self.assertEqual(counter.read_bytes(), original_counter)
        self.assertEqual(self.path.read_bytes(), original_state)
        self.assertEqual(report_gates.storage_path(self.path).read_bytes(), original_gates)
        with self.assertRaisesRegex(UsageError, "blocking VERDICT holds the release"):
            report_gates.require_no_verdict_gate(self.path, "done-00", [{"id": "done-00", "task": "done-00"}])

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
        invalid = "\udcff"
        cases: list[tuple[str, ...]] = [(command, "--task", invalid) for command in ("cost-report", "status", "workflow-readiness")]
        cases.extend([("load-set", "--decision", "brief", "--task", invalid),
                      ("load-set", "--decision", "wake", "--enrollment", invalid),
                      ("load-set", "--decision", "brief", "--task", "one", "--read-file", str(self.root / "report.md"),
                       "--question", invalid),
                      ("github-context", "--reference", REFERENCE, "--question", invalid)])
        for command, *arguments in cases:
            with self.subTest(command=command, arguments=arguments):
                code, out, err = self.call(command, *arguments)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("UTF-8", json.loads(err)["message"])
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
