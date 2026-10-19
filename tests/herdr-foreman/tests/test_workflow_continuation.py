"""Stop coverage is exact and needs the actual implemented executor/resource.

Native APIs are isolated fixtures. Real OS leases/PIDs and existing owner
records execute; these cases are not live Herdr migration or pilot evidence.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import json
import unittest
from unittest.mock import patch

from tests import test_workflow_service as fixture
from foreman import progression_owner, progression_runtime, supervision, supervision_hook
from foreman.errors import UsageError
from foreman.state import save_state


class WorkflowContinuationTest(unittest.TestCase):
    def setUp(self):
        self.case = fixture.WorkflowServiceTest()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def check(self):
        return supervision_hook.check({"cwd": str(Path.cwd()), "session_id": "fixture-session"},
            {"HERDR_ENV": "fixture-only", "HERDR_PANE_ID": "fixture-pane"}, self.case.now(),
            root=self.case.root / "bindings")

    def enroll_legacy(self, task):
        supervision.enroll(self.case.path, {"id": "legacy-uncovered", "agent": "legacy-fixture",
            "task": task, "report": str(self.case.root / "legacy-report.md"), "pane_id": "legacy-pane",
            "native_session": None}, self.case.now())

    def test_unstarted_workflow_blocks_stop_even_without_enrollments(self):
        self.case.admit()
        result = self.check()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["decision"], "block")
        self.assertIn("task executor(s) needing recovery", result["reason"])

    def test_passive_capability_cannot_publish_task_executor_proof(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            with self.assertRaisesRegex(UsageError, "actual admitted task executor"):
                progression_runtime.pulse(capability, self.case.now())
            self.assertIsNotNone(self.check())
            self.case.runner(capability)
            progression_runtime.pulse(capability, self.case.now())
            self.assertIsNone(self.check())
        self.assertIsNotNone(self.check())

    def test_live_executor_covers_its_members_and_never_an_unrelated_obligation(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.case.runner(capability)
            self.case.advance(runner, lambda: bool(self.case.progress()["jobs"]))
            self.assertIsNone(self.check())
            self.enroll_legacy("two")
            result = self.check()
            self.assertIsNotNone(result)
            assert result is not None
            self.assertIn("1 active assignment(s)", result["reason"])

    def test_exception_and_unknown_native_effect_never_borrow_a_live_pulse(self):
        self.case.admit()
        with self.case.owner.session() as capability:
            runner = self.case.runner(capability)
            runner.tick()
            state = self.case.owner.state()
            progress = state["recovery"]["tasks"]["one"]["progression"]
            progress["pending"]["effects_started"] = True
            progress["pending"]["job"]["status"] = "starting"
            save_state(self.case.path, state)
            self.assertIsNotNone(self.check())
            progress.update(phase="exception", exception={"code": "fixture_unknown", "phase": "implement", "sources": [],
                                                         "actions": ["reconcile_original_effect"]})
            save_state(self.case.path, state)
            self.assertIsNotNone(self.check())

    def test_prepared_chain_does_not_gain_stop_delegation_from_current_process_proof(self):
        self.case.owner.contract.write_text(json.dumps({"schema_version": 1, "task": "one", "steps": []}))
        self.case.owner.admit()
        with self.case.owner.session() as capability:
            progression_runtime.pulse(capability, self.case.now())
            self.enroll_legacy("one")
            self.assertIsNotNone(self.check())

    def test_legacy_store_is_not_migrated_or_made_to_reopen_old_contracts_at_stop(self):
        state = self.case.owner.state()
        state["recovery"]["schema_version"] = 18
        save_state(self.case.path, state)
        original = self.case.path.read_bytes()
        with patch.object(progression_owner, "_load", side_effect=AssertionError("Legacy history must not be loaded")):
            self.assertIsNone(self.check())
        self.assertEqual(self.case.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
