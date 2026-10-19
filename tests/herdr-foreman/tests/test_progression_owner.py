"""Real owner transactions and OS leases fence explicit task handoffs."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
import io
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from foreman import cli, progression_owner as owner, recovery, supervision
from foreman.command_context import HerdrCommandContext
from foreman.errors import ForemanError, UsageError
from foreman.state import empty_state, load_state_checked, save_state, state_lock


AT = "2026-10-10T10:00:00+00:00"
ROOT = Path(__file__).resolve().parents[3]
AUTH = {"source": "private unit fixture", "quote": "Delegate this fixture task only."}


class ProgressionOwnerTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name).resolve()
        self.path = self.root / "owner.json"
        state = empty_state()
        for name in ("one", "two"):
            recovery.register_task(state["recovery"], {
                "task": name, "base_revision": "a" * 40, "scope": "Fixture parser correction",
                "allowed_paths": ["src/*"], "authorization": AUTH}, AT)
        save_state(self.path, state)
        self.contract = self.root / "workflow.json"
        self.contract.write_text('{"schema_version": 1, "task": "one"}\n')
        self.native = {"source": "herdr:codex", "agent": "codex", "kind": "id", "value": "fixture-session"}
        self.client = SimpleNamespace(context=HerdrCommandContext("fixture-herdr"), pane_get=lambda pane: {
            "pane_id": pane, "agent_session": self.native})
        self.environment = patch.dict(os.environ, {"HERDR_ENV": "fixture-only", "HERDR_PANE_ID": "fixture-pane"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        identity = supervision.identity("fixture-session", str(Path.cwd()), "fixture-only", pane_id="fixture-pane")
        supervision.bind(self.path, identity, AT, root=self.root / "bindings")
        self.data = {"task": "one", "expected_generation": 0, "authorization": AUTH,
                     "service_id": "fixture-service", "lease_path": str(self.root / "service.lease"),
                     "contract": str(self.contract)}

    def state(self):
        state, usable = load_state_checked(self.path, persist_migration=False)
        self.assertTrue(usable)
        return state

    def admit(self):
        with state_lock(self.path):
            return owner.handoff(self.path, self.data, AT, self.client, ROOT)

    def session(self, generation=1):
        return owner.service_session(self.path, "one", generation, "fixture-service", ROOT)

    def test_explicit_handoff_preserves_other_tasks_and_does_not_dispatch(self):
        before = self.state()
        result = self.admit()
        after = self.state()
        self.assertFalse(result["authorizes_dispatch"])
        self.assertEqual(after["assignments"], before["assignments"])
        self.assertEqual(after["recovery"]["tasks"]["two"], before["recovery"]["tasks"]["two"])
        self.assertEqual(after["recovery"]["events"], before["recovery"]["events"])
        self.assertEqual(after["recovery"]["tasks"]["one"]["schema_version"], 2)
        self.assertEqual(after["recovery"]["tasks"]["one"]["authority"]["generation"], 1)

    def test_standalone_and_wrong_native_callers_cannot_admit(self):
        before = self.path.read_bytes()
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(UsageError, "standalone"):
            self.admit()
        self.native["value"] = "different-session"
        with self.assertRaisesRegex(UsageError, "differs"):
            self.admit()
        self.assertEqual(self.path.read_bytes(), before)

    def test_admission_bounds_the_contract_before_writing_a_grant(self):
        from foreman.progression_service import CONTRACT_BYTES
        self.contract.write_bytes(b" " * (CONTRACT_BYTES + 1))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "byte budget"):
            self.admit()
        self.assertEqual(self.path.read_bytes(), before)

    def test_cli_blocks_legacy_task_mutation_before_other_work(self):
        self.admit()
        record = self.root / "command.json"
        record.write_text(json.dumps({"task": "one"}))
        before = self.path.read_bytes()
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["close-task", "--state", str(self.path), "--record", str(record), "--now", AT],
                        stdout=out, stderr=err, client=self.client)
        self.assertEqual(code, 1)
        self.assertIn("belongs to a progression service", err.getvalue())
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(self.path.read_bytes(), before)
        record.write_text(json.dumps({key: value for key, value in self.state()["recovery"]["tasks"]["two"].items()
                                      if key not in ("schema_version", "at")}))
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(cli.main(["task", "--state", str(self.path), "--record", str(record), "--now", AT],
                                  stdout=out, stderr=err, client=self.client), 0, err.getvalue())

    def test_a_live_service_blocks_another_service_and_return(self):
        self.admit()
        returning = {"task": "one", "expected_generation": 1, "authorization": AUTH}
        with self.session() as capability:
            capability.require_current(self.path, self.state(), "one")
            with self.assertRaisesRegex(ForemanError, "Another progression"):
                with self.session():
                    self.fail("A second process lease was granted")
            with state_lock(self.path), self.assertRaisesRegex(ForemanError, "Another progression"):
                owner.handoff(self.path, returning, AT, self.client, ROOT, returning=True)
        with state_lock(self.path):
            result = owner.handoff(self.path, returning, AT, self.client, ROOT, returning=True)
        self.assertEqual(result["authority"]["generation"], 2)
        self.assertEqual(result["authority"]["mode"], "legacy")
        self.assertIsNone(result["authority"]["contract"])
        with self.assertRaisesRegex(ForemanError, "no longer holds"):
            capability.require_current(self.path, self.state(), "one")

    def test_current_generation_scope_and_contract_are_checked(self):
        self.admit()
        with self.session() as capability:
            with self.assertRaisesRegex(UsageError, "only its admitted"):
                capability.require_current(self.path, self.state(), "two")
            self.contract.write_text('{"schema_version": 1, "task": "changed"}\n')
            with self.assertRaisesRegex(UsageError, "contract changed"):
                capability.require_current(self.path, self.state(), "one")
        with self.assertRaisesRegex(UsageError, "generation changed"):
            with self.session(generation=99):
                self.fail("A stale generation was granted")

    def test_operator_hold_blocks_service_without_resuming_it(self):
        self.admit()
        evidence = self.root / "hold.md"
        evidence.write_text("The fixture operator requires a decision before continuing.\n")
        with self.session() as capability:
            supervision.hold(self.path, {"id": "fixture-hold", "kind": "waiting_for_user",
                                        "resume_condition": "Fixture operator explicitly resumes",
                                        "evidence": [str(evidence)], "dispositions": []}, AT)
            supervision.enroll(self.path, {"id": "unrelated", "agent": "other-worker", "task": "two",
                                          "report": str(self.root / "other.md"), "pane_id": None, "native_session": None}, AT)
            self.assertFalse(supervision.held(supervision.load(self.path)))
            before = supervision.store_path(self.path).read_bytes()
            with self.assertRaisesRegex(UsageError, "operator hold"):
                capability.require_current(self.path, self.state(), "one")
            self.assertEqual(supervision.store_path(self.path).read_bytes(), before)

    def test_changed_hold_boundary_does_not_authorize_admission(self):
        evidence = self.root / "hold.md"
        evidence.write_text("Wait for the fixture operator to resume.\n")
        supervision.hold(self.path, {"id": "fixture-hold", "kind": "waiting_for_user", "resume_condition": "Explicit resume",
                                    "evidence": [str(evidence)], "dispositions": []}, AT)
        supervision.enroll(self.path, {"id": "unrelated", "agent": "other-worker", "task": "two",
                                      "report": str(self.root / "other.md"), "pane_id": None, "native_session": None}, AT)
        self.assertFalse(supervision.held(supervision.load(self.path)))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "operator holds"):
            self.admit()
        self.assertEqual(self.path.read_bytes(), before)

    def test_legacy_migration_never_invents_service_authority(self):
        state = self.state()
        state["recovery"]["schema_version"] = 18
        original = copy.deepcopy(state["recovery"]["tasks"])
        save_state(self.path, state)
        migrated, usable = load_state_checked(self.path)
        self.assertTrue(usable)
        self.assertEqual(migrated["recovery"]["schema_version"], 19)
        self.assertEqual(migrated["recovery"]["tasks"], original)
        self.admit()
        unowned = copy.deepcopy(self.state()["recovery"])
        unowned["schema_version"] = 18
        before = copy.deepcopy(unowned)
        with self.assertRaisesRegex(UsageError, "unowned task authority"):
            recovery.migrate_store(unowned)
        self.assertEqual(unowned, before)

    def test_cli_capability_cannot_cross_task_or_command_boundaries(self):
        self.admit()
        with self.session() as capability:
            for command in (SimpleNamespace(command="apply", task="two"),
                            SimpleNamespace(command="start-foreman", task="one")):
                with state_lock(self.path), self.assertRaisesRegex(UsageError, "does not authorize"):
                    owner.require_command(self.path, command, capability)

    def test_pending_dispatch_and_active_enrollment_prevent_admission(self):
        state = self.state()
        recovery.reserve(state["recovery"], {"id": "pending-one", "fingerprint": "c" * 64,
                         "task": "one", "role": "developer", "agent": "fixture-worker", "fix_round": None,
                         "plan": None, "work": None}, AT)
        save_state(self.path, state)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "pending sends"):
            self.admit()
        self.assertEqual(self.path.read_bytes(), before)
        recovery.abort_pre_send(state["recovery"], "pending-one", AT, "fixture proved no send")
        save_state(self.path, state)
        supervision.enroll(self.path, {"id": "active-one", "task": "one", "agent": "fixture-worker",
                          "report": str(self.root / "report.md"), "pane_id": None, "native_session": None}, AT)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "active enrollments"):
            self.admit()
        self.assertEqual(self.path.read_bytes(), before)

    def test_unbounded_grant_is_refused_before_state_changes(self):
        self.data["authorization"] = {**AUTH, "quote": "x" * 5_000}
        before = self.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "grant bounded"):
            self.admit()
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
