"""One held row cannot erase history or stop unrelated owner transactions."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from copy import deepcopy
import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch

from foreman import context_evidence, progression_owner, recovery, supervision, task_evidence, workflow_readiness
from foreman.errors import StateError, UsageError
from foreman.process_lease import process_lease
from foreman.state import _NoUsableState, _validate, add_assignment, empty_state, load_state_checked, save_state
from tests import test_cli as fixture
from tests.fakes import FakeRunner

AT = fixture.AT
BASE = "a" * 40
HEAD = "b" * 40
AUTH = {"source": "fixture operator", "quote": "Authorize the independent tasks within their recorded source scope."}


class TaskEvidenceTests(fixture.CliCase):
    _client = fixture.ApplyCommandTest._client

    def setUp(self):
        super().setUp()
        self.runner = FakeRunner()
        environment = patch.dict(os.environ, {"XDG_STATE_HOME": str(self.tmp / "xdg")})
        environment.start()
        self.addCleanup(environment.stop)
        self.identity = supervision.identity("bound-foreman", str(self.tmp), "fixture", pane_id="foreman-pane")
        supervision.bind(self.state, self.identity, AT)
        value = empty_state()
        for task in ("held", "valid", "next", "unknown-send", "service-task"):
            recovery.register_task(value["recovery"], {"task": task, "base_revision": BASE,
                "scope": "Independent fixture source scope", "allowed_paths": ["src/*"], "authorization": AUTH}, AT)
        for _ in range(1_528):
            add_assignment(value, AT, "tester", "historic-contributor", task="historic-task")
        for task, worker in (("held", "held-worker"), ("valid", "valid-worker")):
            add_assignment(value, AT, "developer", worker, task=task)
            record = {"id": task + ":developer", "task": task, "role": "developer", "agent": worker,
                      "fix_round": None, "fingerprint": task * 8, "plan": None, "work": None, "worker_kind": "claude"}
            recovery.reserve(value["recovery"], record, AT)
            result = {"status": "applied", "task": task, "role": "developer", "agent": worker,
                      "fix_round": None, "assignment_scoped": True, "worker_kind": "claude",
                      "cleared": True if task == "held" else None,
                      "clear_reason": "hand" if task == "held" else "unknown", "context_session": None}
            recovery.finish_dispatch(value["recovery"], record["id"], result, len(value["assignments"]) - 1, AT)
        self.held_index = 1_528
        value["assignments"][self.held_index].update(cleared=True, clear_reason="hand")
        recovery.reserve(value["recovery"], {"id": "unknown:developer", "task": "unknown-send", "role": "developer",
            "agent": "unknown-worker", "fix_round": None, "fingerprint": "c" * 64, "plan": None, "work": None}, AT)
        recovery.mark_sending(value["recovery"], "unknown:developer", AT,
                              {"cleared": None, "clear_reason": "unknown", "context_session": None})
        value["recovery"]["tasks"]["service-task"].update(schema_version=2, authority={
            "schema_version": 2, "generation": 3, "mode": "service", "service_id": "original-service",
            "lease_path": str(self.tmp / "service.lease"), "contract": {"path": str(self.tmp / "contract.json"), "sha256": "d" * 64},
            "contract_schema": 1, "policy": {"version": "0.16.2", "digest": "e" * 64},
            "binding": {"generation": 1, "digest": "f" * 64}, "authorization": AUTH, "at": AT})
        self.original = (json.dumps(value, indent=2) + "\n").encode()
        self.state.write_bytes(self.original)
        self.original_value = deepcopy(value)
        supervision.enroll(self.state, {"id": "held:developer", "agent": "held-worker", "task": "held",
            "report": str(self.tmp / "held-report.md"), "pane_id": "held-pane", "native_session": None}, AT)
        self.hold_evidence = self.tmp / "operator.md"
        self.hold_evidence.write_text("Fixture operator boundary evidence.\n")
        supervision.hold(self.state, self.hold_record("past-operator"), AT)
        supervision.resume(self.state, AT, expected_holds=["past-operator"])
        self.supervised = supervision.load(self.state)
        self.report = self.tmp / "valid-review.md"
        self.report.write_text("VERDICT: approved\nCurrent independent full review at " + HEAD + "\n")

    def invoke(self, arguments, client=None):
        self.out, self.err = io.StringIO(), io.StringIO()
        return self.run_cli(self.base() + arguments, client=client)

    def hold_record(self, identifier):
        return {"id": identifier, "kind": "waiting_for_user", "resume_condition": "Wait for the operator",
                "evidence": [str(self.hold_evidence)], "dispositions": [{"member": "held:developer",
                "outcome": "Retain the actual worker assignment", "evidence": [str(self.hold_evidence)]}]}

    def owner(self, command, record):
        path = self.tmp / (command + ".json")
        path.write_text(json.dumps(record))
        return self.invoke([command, "--record", str(path), "--now", AT])

    def report_record(self, dispatch="valid:developer"):
        return {"dispatch": dispatch, "head_revision": HEAD, "verdict": "approved", "review_mode": "full",
                "reviewer": "independent-reviewer", "report": str(self.report), "changed_paths": ["src/parser.py"]}

    def apply_arguments(self, task="next"):
        report = self.tmp / "next-report.md"
        self.assign_report(self.briefs["developer"], str(report))
        return ["apply", "--task", task, "--assignments", '{"developer":"grok"}', "--common", str(self.common),
                "--brief", "developer=" + str(self.briefs["developer"]), "--report", "developer=" + str(report),
                "--dispatch-id", "next-dispatch", "--composer-settle", "0", "--now", AT]

    def test_unrelated_report_and_dispatch_continue_without_repairing_or_accepting_held_row(self):
        value, usable = load_state_checked(self.state, warn=lambda _message: None, persist_migration=False)
        self.assertTrue(usable)
        self.assertEqual(value, self.original_value)
        self.assertEqual(self.state.read_bytes(), self.original)
        self.assertFalse(Path(str(self.state) + ".task-evidence").exists(), "Read-only inspection must not write evidence")
        code, out, err = self.owner("record-report", self.report_record())
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["dispatch"], "valid:developer")
        code, out, err = self.invoke(self.apply_arguments(), self._client({"grok": "idle"}))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(json.loads(out)["applied"]), 1)
        actual, usable = load_state_checked(self.state, warn=lambda _message: None, persist_migration=False)
        self.assertTrue(usable)
        self.assertEqual(actual["assignments"][:1_530], self.original_value["assignments"])
        self.assertEqual(len(actual["assignments"]), 1_531)
        before_dispatches = self.original_value["recovery"]["dispatches"]
        self.assertEqual(actual["recovery"]["dispatches"][0], before_dispatches[0])
        self.assertIsNone(actual["recovery"]["dispatches"][0]["report"])
        self.assertEqual(actual["recovery"]["dispatches"][2], before_dispatches[2], "Unknown transport must remain unknown")
        self.assertEqual(actual["recovery"]["tasks"], self.original_value["recovery"]["tasks"])
        self.assertEqual(supervision.load(self.state)["members"][0], self.supervised["members"][0])
        self.assertEqual(supervision.load(self.state)["binding"], self.supervised["binding"])
        self.assertEqual(supervision.load(self.state)["holds"], self.supervised["holds"])
        self.assertEqual(actual["recovery"]["events"][:len(self.original_value["recovery"]["events"])], self.original_value["recovery"]["events"])
        backup = Path(str(self.state) + ".task-evidence") / (hashlib.sha256(self.original).hexdigest() + ".original.json")
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(backup.parent.stat().st_mode & 0o777, 0o700)
        receipts = [path for path in backup.parent.iterdir() if not path.name.endswith(".original.json")]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())["fault"]["assignment_index"], self.held_index)
        # Existing owner traces show dispatch proceeded at the supplied tick;
        # isolation adds no repair phase, wait interval or bookkeeping command.
        self.assertEqual(actual["recovery"]["dispatches"][-1]["at"], AT)

    def test_held_task_reports_dispatches_closures_and_enrollment_acceptance_refuse(self):
        client = self._client({"grok": "idle"})
        commands = [self.apply_arguments("held"), ["relaunch-worker", "held-worker", "--now", AT],
                    ["close-member", "--enrollment", "held:developer", "--ledger", str(self.tmp / "unused.md")]]
        for arguments in commands:
            with self.subTest(command=arguments[0]):
                code, out, err = self.invoke(arguments, client)
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertIn("task_evidence_held", err)
                self.assertEqual(self.state.read_bytes(), self.original)
        code, _, err = self.owner("record-report", self.report_record("held:developer"))
        self.assertEqual(code, 1)
        self.assertIn("task_evidence_held", err)
        code, _, err = self.owner("close-task", {"task": "held", "outcome": "merged", "evidence": "must stay held"})
        self.assertEqual(code, 1)
        self.assertIn("task_evidence_held", err)
        self.assertEqual(self.runner.calls, [], "No held transition may reach native transport")
        self.assertEqual(supervision.load(self.state), self.supervised)

    def test_status_reports_exact_row_dispatch_unknown_outcome_and_coverage(self):
        code, out, err = self.invoke(["status", "--task", "held"])
        self.assertEqual(code, 0, err)
        diagnostic = json.loads(out)["task_evidence"]
        self.assertTrue(diagnostic["held"])
        self.assertEqual(diagnostic["total"], 1)
        self.assertEqual(diagnostic["affected_rows"][0]["assignment_index"], self.held_index)
        self.assertEqual(diagnostic["affected_rows"][0]["dispatch"], "held:developer")
        self.assertEqual(diagnostic["affected_rows"][0]["outcome"], "unknown")
        code, out, err = self.invoke(["status", "--task", "valid"])
        self.assertEqual(code, 0, err)
        self.assertFalse(json.loads(out)["task_evidence"]["held"])

    def test_service_and_readiness_boundaries_refuse_only_the_held_scope(self):
        with process_lease(self.tmp / "held-service.lease") as lease:
            capability = progression_owner.ServiceCapability(state_path=self.state, task="held", generation=3,
                service_id="held-service", lease=lease, plugin_root=Path(__file__).resolve().parents[3])
            with self.assertRaises(UsageError) as failure:
                capability.require_current(self.state, self.original_value, "held")
            self.assertEqual(failure.exception.details["reason"], "task_evidence_held")
        with self.assertRaises(UsageError) as failure:
            workflow_readiness.current_inputs(self.original_value, self.state, "held", self.supervised, self.tmp)
        self.assertEqual(failure.exception.details["reason"], "task_evidence_held")
        with self.assertRaises(UsageError) as failure:
            workflow_readiness.current_inputs(self.original_value, self.state, "valid", self.supervised, self.tmp)
        self.assertEqual(failure.exception.details["reason"], "task_not_admitted")

    def test_unattributable_context_and_other_corruption_still_refuse_global_owner(self):
        for corrupt in ("missing_task", "duplicate_dispatch", "other_field", "service_authority"):
            with self.subTest(corrupt=corrupt):
                value = deepcopy(self.original_value)
                if corrupt == "missing_task":
                    value["assignments"][self.held_index]["task"] = None
                elif corrupt == "duplicate_dispatch":
                    value["recovery"]["dispatches"].append(deepcopy(value["recovery"]["dispatches"][0]))
                elif corrupt == "other_field":
                    value["assignments"][self.held_index]["tier"] = {"verified": False}
                else:
                    value["recovery"]["tasks"]["service-task"]["authority"]["binding"]["generation"] = 0
                body = json.dumps(value).encode()
                self.state.write_bytes(body)
                code, _, _err = self.owner("record-report", self.report_record())
                self.assertEqual(code, 1)
                self.assertEqual(self.state.read_bytes(), body)
                self.assertFalse(load_state_checked(self.state, warn=lambda _message: None)[1])

    def test_global_supervision_binding_corruption_and_operator_holds_still_stop_dispatch(self):
        path = supervision.store_path(self.state)
        for field in ("binding", "holds"):
            with self.subTest(field=field):
                changed = deepcopy(self.supervised)
                if field == "binding":
                    changed["binding"]["generation"] = 0
                    path.write_text(json.dumps(changed))
                else:
                    path.write_text(json.dumps(self.supervised))
                    supervision.hold(self.state, self.hold_record("operator"), AT)
                    self.assertIsNone(supervision.load(self.state)["holds"][-1]["resumed_at"])
                code, _out, err = self.invoke(self.apply_arguments(), self._client({"grok": "idle"}))
                self.assertEqual(code, 1)
                self.assertFalse(any("prompt" in call or "send-text" in call for call in self.runner.calls), err)
                self.assertEqual(self.state.read_bytes(), self.original)

    def test_preservation_failure_or_changed_evidence_never_rewrites_owner(self):
        with patch.object(task_evidence, "_publish", side_effect=StateError("fixture preservation refused", {})):
            code, _, err = self.owner("record-report", self.report_record())
        self.assertEqual(code, 1)
        self.assertIn("preservation refused", err)
        self.assertEqual(self.state.read_bytes(), self.original)
        code, _, err = self.owner("record-report", self.report_record())
        self.assertEqual(code, 0, err)
        before = self.state.read_bytes()
        backup = next(Path(str(self.state) + ".task-evidence").glob("*.original.json"))
        backup.write_text("changed")
        with self.assertRaisesRegex(StateError, "original task evidence backup"):
            save_state(self.state, json.loads(before))
        self.assertEqual(self.state.read_bytes(), before)

    def test_unsupported_receipts_and_symlinked_private_evidence_refuse_preserving_owner(self):
        code, _, err = self.owner("record-report", self.report_record())
        self.assertEqual(code, 0, err)
        root = Path(str(self.state) + ".task-evidence")
        receipt = next(path for path in root.iterdir() if not path.name.endswith(".original.json"))
        record = json.loads(receipt.read_text())
        before = self.state.read_bytes()
        for version in (0, 2, True, None):
            with self.subTest(version=version):
                receipt.write_text(json.dumps({**record, "schema_version": version}))
                with self.assertRaisesRegex(StateError, "schema-1 original"):
                    save_state(self.state, json.loads(before))
                self.assertEqual(self.state.read_bytes(), before)
        receipt.write_text(json.dumps(record))
        retained = root.with_name(root.name + "-retained")
        root.rename(retained)
        root.symlink_to(retained, target_is_directory=True)
        with self.assertRaisesRegex(StateError, "private mode 0700"):
            save_state(self.state, json.loads(before))
        self.assertEqual(self.state.read_bytes(), before)

    def test_narrow_context_quarantine_validation_is_not_a_generic_waiver(self):
        with self.assertRaises(_NoUsableState):
            _validate(deepcopy(self.original_value), self.state)
        data = {"schema_version": 1, "id": "exact-repair", "assignment_index": self.held_index,
                "assignment_sha256": context_evidence.digest(self.original_value["assignments"][self.held_index]),
                "dispatch": "held:developer", "authorization": AUTH}
        with patch.object(context_evidence.progression_owner, "verify_foreman", return_value={}):
            result = context_evidence.quarantine(self.state, data, AT, object())
        self.assertTrue(result["quarantined"])
        actual, usable = load_state_checked(self.state, warn=lambda _message: None)
        self.assertTrue(usable)
        self.assertFalse(task_evidence.view(actual)["held"])
        self.assertIsNone(actual["assignments"][self.held_index]["cleared"])


if __name__ == "__main__":
    unittest.main()
