"""Both channel readers land before one shared owner-writer activation."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

from foreman import engagement, recovery, release_activation, report_delivery, workflow_recovery
from foreman.errors import UsageError
from foreman.state import empty_state, load_state_checked, save_state
from tests import test_engagement as assessment_fixture
from tests import test_workflow_recovery as workflow_fixture, test_workflow_service as service_fixture


class ReleaseActivationTest(unittest.TestCase):
    def assessment_case(self):
        case = assessment_fixture.EngagementTest()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_default_flag_has_no_environment_or_record_activation_route(self):
        self.assertFalse(release_activation.enabled())
        with patch.dict(os.environ, {"HERDR_NEW_OWNER_WRITES_ENABLED": "1", "NEW_OWNER_WRITES_ENABLED": "true"}):
            self.assertFalse(release_activation.enabled())
            with self.assertRaises(UsageError) as failure:
                release_activation.require("Fixture owner")
        self.assertEqual(failure.exception.details["reason"], "owner_writes_staged")

    def test_legacy_recovery_writes_stay_nineteen_and_both_versions_read_without_downgrade(self):
        state = empty_state()
        self.assertEqual(state["recovery"]["schema_version"], 19)
        original = deepcopy(state["recovery"])
        self.assertFalse(recovery.migrate_store(state["recovery"]))
        self.assertEqual(state["recovery"], original)
        with patch.object(recovery, "RECOVERY_STORE_VERSION", 19):
            recovery.validate_store(state["recovery"], [])
        state["recovery"]["schema_version"] = 20
        original = deepcopy(state["recovery"])
        self.assertFalse(recovery.migrate_store(state["recovery"]))
        recovery.validate_store(state["recovery"], [])
        self.assertEqual(state["recovery"], original)
        with patch.object(recovery, "RECOVERY_STORE_VERSION", 19), self.assertRaises(UsageError):
            recovery.validate_store(state["recovery"], [])
        illegal = {**original, "schema_version": 19, "events": [{"kind": "progression_measurement_reconciled"}]}
        before = deepcopy(illegal)
        with self.assertRaisesRegex(UsageError, "unowned measurement reconciliation"):
            recovery.validate_store(illegal, [])
        self.assertEqual(illegal, before)

    def test_legacy_assessment_writes_and_owner_migration_keep_exact_schema_two_fields(self):
        case = self.assessment_case()
        with patch.object(release_activation, "NEW_OWNER_WRITES_ENABLED", False):
            case.state["recovery"]["schema_version"] = 19
            record = case.assess()
            self.assertEqual(record["schema_version"], 2)
            self.assertEqual(set(record), engagement.PREVIOUS_FIELDS)
            self.assertNotIn("native_delivery", record)
            case.state["specialist_assessments"] = [assessment_fixture.legacy_record(record)]
            self.assertTrue(engagement.migrate_assessments(case.state))
            migrated = case.state["specialist_assessments"][0]
            self.assertEqual(migrated["schema_version"], 2)
            self.assertEqual(set(migrated), engagement.PREVIOUS_FIELDS)
            engagement.validate_assessments(case.state)
            save_state(case.path, case.state)
            before = case.path.read_bytes()
            self.assertTrue(load_state_checked(case.path, persist_migration=False)[1])
            self.assertEqual(case.path.read_bytes(), before)

    def test_new_native_proof_writes_refuse_but_existing_schema_four_history_remains_usable(self):
        case = self.assessment_case()
        record, _dispatch, _source = case.native_assessment()
        with patch.object(release_activation, "NEW_OWNER_WRITES_ENABLED", False):
            save_state(case.path, case.state)
            before = case.path.read_bytes()
            with patch.object(report_delivery, "verify_native_assessment", side_effect=AssertionError("Historical reads must not open native history")):
                loaded, usable = load_state_checked(case.path, persist_migration=False)
            self.assertTrue(usable)
            self.assertEqual(case.path.read_bytes(), before)
            self.assertEqual(engagement.require_accepted(loaded, record["dispatch"], record["report"]), record)
            original = deepcopy(case.state)
            with self.assertRaises(UsageError) as failure:
                case.assess({**case.data, "id": "staged-new-proof"})
            self.assertEqual(failure.exception.details["reason"], "owner_writes_staged")
            self.assertEqual(case.state, original)
            self.assertEqual(case.path.read_bytes(), before)

    def test_shared_activation_enables_both_owners_without_per_schema_input(self):
        case = self.assessment_case()
        with patch.object(release_activation, "NEW_OWNER_WRITES_ENABLED", True):
            self.assertEqual(recovery.empty_recovery()["schema_version"], 20)
            record, _dispatch, _source = case.native_assessment()
            self.assertEqual(record["schema_version"], 4)
            self.assertEqual(record["native_delivery"]["schema_version"], 1)

    def test_measurement_reconciliation_is_staged_without_clearing_original_pending_intent(self):
        case = workflow_fixture.WorkflowRecoveryTest()
        case.setUp()
        self.addCleanup(case.doCleanups)
        intent = case.pending_measurement()
        data = {"task": "one", "expected_generation": 1, "intent": intent["id"],
                "authorization": workflow_fixture.fixture.owner_fixture.AUTH,
                "readback": {"schema_version": 1, "kind": "snapshot_completed", "sha256": "a" * 64}}
        state = case.case.owner.state()
        grant = state["recovery"]["tasks"]["one"]["authority"]
        supervised = workflow_fixture.supervision.load(case.case.path)
        before = case.case.path.read_bytes()
        original = deepcopy(state)
        with patch.object(release_activation, "NEW_OWNER_WRITES_ENABLED", False), self.assertRaises(UsageError) as failure:
            workflow_recovery.reconcile_measurement(case.case.path, state, grant, supervised,
                case.case.document, data, case.case.now(), case.case.owner.client)
        self.assertEqual(failure.exception.details["reason"], "owner_writes_staged")
        self.assertEqual(case.case.path.read_bytes(), before)
        self.assertEqual(state, original)

    def test_default_measurement_intent_keeps_deployed_enclosing_shape(self):
        case = service_fixture.WorkflowServiceTest()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.admit()
        state = case.owner.state()
        state["snapshots"] = []
        save_state(case.path, state)
        with case.owner.session() as capability:
            self.assertEqual(case.runner(capability).tick()["data"]["status"], "prepared")
        self.assertEqual(case.progress()["pending"]["argv"], [])
        self.assertEqual(case.owner.state()["recovery"]["schema_version"], 19)
        with patch.object(recovery, "RECOVERY_STORE_VERSION", 19):
            self.assertTrue(load_state_checked(case.path, persist_migration=False)[1])

    def test_existing_new_measurement_receipt_replays_without_new_staged_writes(self):
        case = workflow_fixture.WorkflowRecoveryTest()
        case.setUp()
        self.addCleanup(case.doCleanups)
        intent = case.pending_measurement()
        state = case.case.owner.state()
        state["recovery"]["tasks"]["one"]["progression"]["pending"]["effects_started"] = False
        intent["effects_started"] = False
        save_state(case.case.path, state)
        data, result = case.reconcile_measurement(intent, "intent_not_started", intent)
        self.assertFalse(result["replayed"])
        before = case.case.path.read_bytes()
        with patch.object(release_activation, "NEW_OWNER_WRITES_ENABLED", False):
            _data, replay = case.reconcile_measurement(intent, "intent_not_started", intent)
        self.assertTrue(replay["replayed"])
        self.assertEqual(case.case.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
