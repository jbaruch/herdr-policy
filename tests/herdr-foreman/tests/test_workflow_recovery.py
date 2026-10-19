"""Recovery and CLI lifetime against real isolated owner/kernel/Git state."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import io
import json
import unittest
from unittest.mock import patch

from tests import test_workflow_service as fixture
from tests import test_report_gates as gate_fixture
from foreman import cli, process_lease, progression_owner as authority
from foreman import recovery, supervision, workflow_recovery, workflow_service
from foreman.errors import ForemanError, UsageError
from foreman.state import add_snapshot, latest_snapshot, save_state, state_lock


class WorkflowRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.case = fixture.WorkflowServiceTest()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.admit()

    def exception(self, code="workflow_owner_refused", *, at=None):
        with self.case.owner.session() as capability:
            engine = self.case.runner(capability)
            if at is not None:
                engine.clock = lambda: at
            with state_lock(self.case.path):
                result = engine._exception(self.case.owner.state(), code, [str(self.case.path)])
        return {"task": "one", "expected_generation": 1, "exception": result["data"]["exception_digest"],
                "authorization": fixture.owner_fixture.AUTH}

    def resume(self, data):
        with state_lock(self.case.path):
            return workflow_recovery.resume(self.case.path, data, self.case.now(), self.case.owner.client, fixture.ROOT)

    def test_resume_preserves_phase_task_counter_and_is_idempotent(self):
        data = self.exception()
        before = self.case.owner.state()
        self.assertFalse(self.resume(data)["replayed"])
        after = self.case.owner.state()
        self.assertEqual(after["recovery"]["tasks"]["two"], before["recovery"]["tasks"]["two"])
        self.assertEqual(after["recovery"]["tasks"]["one"]["authority"], before["recovery"]["tasks"]["one"]["authority"])
        self.assertEqual(self.case.progress()["round"], 0)
        self.assertEqual(self.case.progress()["phase"], "implement")
        saved = self.case.path.read_bytes()
        self.assertTrue(self.resume(data)["replayed"])
        self.assertEqual(self.case.path.read_bytes(), saved)

    def test_packet_substitution_live_lease_and_operator_hold_refuse_resume(self):
        data = self.exception()
        before = self.case.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "exact retryable"):
            self.resume({**data, "exception": "0" * 64})
        with self.case.owner.session(), self.assertRaisesRegex(ForemanError, "Another progression"):
            self.resume(data)
        supervision.hold(self.case.path, {"id": "fixture-hold", "kind": "waiting_for_user",
            "resume_condition": "Explicit fixture operator resumes", "evidence": [str(self.case.common)],
            "dispositions": []}, self.case.now())
        with self.assertRaisesRegex(UsageError, "operator hold"):
            self.resume(data)
        self.assertEqual(self.case.path.read_bytes(), before)

    def test_consumed_authorization_never_resumes_a_later_identical_failure(self):
        at = "2026-10-19T00:00:00+00:00"
        original = self.exception(at=at)
        self.resume(original)
        current = self.exception(at=at)
        self.assertNotEqual(current["exception"], original["exception"])
        saved = self.case.path.read_bytes()
        self.assertTrue(self.resume(original)["replayed"])
        self.assertEqual(self.case.path.read_bytes(), saved)
        self.assertEqual(self.case.progress()["phase"], "exception")
        self.assertFalse(self.resume(current)["replayed"])

    def test_admission_exclusively_reserves_the_artifact_directory(self):
        writer = self.case.root / "other-writer"
        self.case.git("worktree", "add", "-b", "feature/other", str(writer))
        document = json.loads(json.dumps(self.case.document))
        document["task"] = "two"
        document["repository"].update(worktree=str(writer), branch="feature/other")
        contract = self.case.root / "other-workflow.json"
        contract.write_text(json.dumps(document))
        state = self.case.owner.state()
        state["recovery"]["tasks"]["two"]["base_revision"] = self.case.base
        save_state(self.case.path, state)
        before = self.case.path.read_bytes()
        data = {**self.case.owner.data, "task": "two", "service_id": "fixture-two",
                "lease_path": str(self.case.root / "other.lease"), "contract": str(contract)}
        with state_lock(self.case.path), self.assertRaisesRegex(UsageError, "fresh private artifact directory"):
            authority.handoff(self.case.path, data, self.case.now(), self.case.owner.client, fixture.ROOT)
        self.assertEqual(self.case.path.read_bytes(), before)
        self.assertEqual(list(Path(document["artifact_directory"]).iterdir()), [])

    def test_decisions_and_unknown_native_send_are_not_retryable(self):
        data = self.exception("verification_decision_required")
        with self.assertRaisesRegex(UsageError, "decision owner"):
            self.resume(data)
        # Restore a fixture observation stage, then exercise actual launch
        # callbacks with an unknown native transport result.
        state = self.case.owner.state()
        state["recovery"]["tasks"]["one"]["progression"].update(phase="implement", exception=None)
        save_state(self.case.path, state)
        self.case.native.reject_prompt = True
        with self.case.owner.session() as capability:
            engine = self.case.runner(capability)
            engine.tick()
            result = engine.tick()
        data["exception"] = result["data"]["exception_digest"]
        before = self.case.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "unknown native effect"):
            self.resume(data)
        intent = self.case.progress()["pending"]["id"]
        with state_lock(self.case.path), self.assertRaisesRegex(UsageError, "owner-proved not_sent"):
            authority.reconcile_intent(self.case.path, {"task": "one", "expected_generation": 1,
                "intent": intent, "authorization": data["authorization"]}, self.case.now(), self.case.owner.client)
        self.assertEqual(self.case.path.read_bytes(), before)

    def test_a_task_exception_does_not_prevent_an_unrelated_task_from_launching(self):
        self.exception("verification_decision_required")
        writer = self.case.root / "other-writer"
        self.case.git("worktree", "add", "-b", "feature/other", str(writer))
        document = json.loads(json.dumps(self.case.document))
        document.update(task="two", artifact_directory=str(self.case.root / "other-current"))
        document["repository"].update(worktree=str(writer), branch="feature/other")
        contract = self.case.root / "other-workflow.json"
        contract.write_text(json.dumps(document))
        state = self.case.owner.state()
        state["recovery"]["tasks"]["two"]["base_revision"] = self.case.base
        save_state(self.case.path, state)
        data = {**self.case.owner.data, "task": "two", "service_id": "fixture-two",
                "lease_path": str(self.case.root / "other.lease"), "contract": str(contract)}
        with state_lock(self.case.path):
            authority.handoff(self.case.path, data, self.case.now(), self.case.owner.client, fixture.ROOT)
        with authority.service_session(self.case.path, "two", 1, "fixture-two", fixture.ROOT) as capability:
            runner = self.case.runner(capability)
            runner.tick()
            runner.tick()
            self.assertEqual(runner.tick()["data"]["status"], "advanced")
        self.assertEqual(self.case.progress()["phase"], "exception")
        active = [row for row in supervision.load(self.case.path)["members"] if row["active"]]
        self.assertEqual([row["assignment"]["task"] for row in active], ["two"])

    def test_owner_proved_no_send_replans_fresh_identity_without_resetting_task(self):
        with self.case.owner.session() as capability:
            self.case.runner(capability).tick()
        state = self.case.owner.state()
        original = self.case.progress()["pending"]
        proof = self.case.root / "fixture-native-proof.json"
        proof.write_text('{"fixture": "original startup never existed and no prompt was sent"}\n')
        recovery.reconcile(state["recovery"], state["assignments"], {"dispatch": original["job"]["id"],
            "outcome": "not_sent", "reason": "Private native owner fixture", "authorization": fixture.owner_fixture.AUTH,
            "evidence": str(proof)}, self.case.now(), None, missing_bootstrap=True)
        save_state(self.case.path, state)
        data = {"task": "one", "expected_generation": 1, "intent": original["id"],
                "authorization": fixture.owner_fixture.AUTH}
        for replay in (False, True):
            with state_lock(self.case.path):
                result = authority.reconcile_intent(self.case.path, data, self.case.now(), self.case.owner.client)
            self.assertEqual(result["replayed"], replay)
        with self.case.owner.session() as capability:
            self.case.runner(capability).tick()
        current = self.case.progress()
        self.assertNotEqual(current["pending"]["job"]["id"], original["job"]["id"])
        self.assertNotEqual(current["pending"]["job"]["agent"], original["job"]["agent"])
        self.assertEqual(current["round"], 0)
        self.assertEqual([row["status"] for row in self.case.owner.state()["recovery"]["dispatches"]], ["not_sent", "reserved"])

    def test_confirmed_native_apply_resumes_by_readback_without_another_launch(self):
        with self.case.owner.session() as capability:
            engine = self.case.runner(capability)
            engine.tick()
            engine.tick()
            with state_lock(self.case.path):
                result = engine._exception(self.case.owner.state(), "pending_effect_requires_reconciliation")
        data = {"task": "one", "expected_generation": 1, "exception": result["data"]["exception_digest"],
                "authorization": fixture.owner_fixture.AUTH}
        record = self.case.root / "resume.json"
        record.write_text(json.dumps(data))
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(cli.main(["progression-resume", "--state", str(self.case.path), "--record", str(record),
            "--now", self.case.now()], stdout=out, stderr=err, client=self.case.owner.client), 0, err.getvalue())
        self.assertFalse(json.loads(out.getvalue())["authorizes_dispatch"])
        with self.case.owner.session() as capability, patch.object(self.case.native, "workspace_create", wraps=self.case.native.workspace_create) as spawn:
            self.assertEqual(self.case.runner(capability).tick()["data"]["status"], "advanced")
            spawn.assert_not_called()
        self.assertEqual(len(self.case.owner.state()["assignments"]), 1)

    def test_classifier_gate_holds_release_before_any_native_launch(self):
        with self.case.owner.session() as capability:
            engine = self.case.runner(capability)
            self.case.advance(engine, lambda: self.case.progress()["pending"] is not None
                and self.case.progress()["pending"]["job"] is not None
                and self.case.progress()["pending"]["job"]["role"] == "release", delivery=self.case.deliver)
            developer = self.case.owner.state()["recovery"]["dispatches"][0]
            report = next(row["assignment"]["report"] for row in supervision.load(self.case.path)["members"] if row["id"] == developer["id"])
            fixture.report_gates.record(self.case.path, {"schema_version": 2, "agent": "default", "labels": [
                gate_fixture.label(Path(report), gate_fixture.HIGH)], "unannotated": []}, self.case.now())
            with patch.object(self.case.native, "workspace_create", wraps=self.case.native.workspace_create) as spawn:
                result = engine.tick()
                spawn.assert_not_called()
        self.assertTrue(result["wake_agent"])
        self.assertIn("open block gate", result["data"]["exception"]["sources"][-1])
        self.assertFalse(self.case.progress()["pending"]["effects_started"])

    def test_cli_once_constructs_real_executor_and_releases_heartbeat_and_lease(self):
        original = workflow_service.WorkflowService
        case = self.case
        class Constructed(original):
            def __init__(self, capability, client, **_options):
                case.native.capability = capability
                capability.authorized_client = lambda _client: case.native
                super().__init__(capability, client, clock=case.now, sleeper=lambda _: None,
                                 native=case.adapter, planner=case.plan)
        out, err = io.StringIO(), io.StringIO()
        with patch("foreman.workflow_service.WorkflowService", Constructed), patch("foreman.cli.now_iso", side_effect=case.now):
            code = cli.main(["progression-run", "--state", str(self.case.path), "--task", "one",
                "--generation", "1", "--service-id", "fixture-service", "--once"],
                stdout=out, stderr=err, client=self.case.native)
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue())["data"]["status"], "prepared")
        watcher = supervision.load(self.case.path)["watchers"][-1]
        self.assertEqual(watcher["schema_version"], 2)
        self.assertEqual(watcher["status"], "stopped")
        self.assertFalse(process_lease.held(self.case.owner.data["lease_path"]))

    def test_measurement_owner_saved_state_is_reloaded_without_lost_updates(self):
        state = self.case.owner.state()
        state["snapshots"] = []
        save_state(self.case.path, state)
        with self.case.owner.session() as capability:
            engine = self.case.runner(capability)
            engine.tick()
            self.assertEqual(self.case.progress()["pending"]["operation"], "measure")
            def measured(_args, *, client):
                saved = self.case.owner.state()
                add_snapshot(saved, {"schema_version": 5, "measured_at": self.case.now(), "agents": {},
                                     "failed_agents": [], "skipped_agents": []})
                saved["recovery"]["tasks"]["two"]["scope"] = "Updated by the fixture measurement owner"
                save_state(self.case.path, saved)
                return {}, None
            with patch("foreman.cli.cmd_measure", side_effect=measured):
                self.assertEqual(engine.tick()["data"]["status"], "advanced")
        after = self.case.owner.state()
        self.assertIsNotNone(latest_snapshot(after))
        self.assertEqual(after["recovery"]["tasks"]["two"]["scope"], "Updated by the fixture measurement owner")
        self.assertIsNone(self.case.progress()["pending"])


if __name__ == "__main__":
    unittest.main()
