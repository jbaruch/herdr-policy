"""Aggregate output allowances survive repeated processes and preserve gates."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from foreman import decision_budget as budget
from foreman.errors import StateError, UsageError
from foreman.load_set import build, read_evidence
from foreman.recovery import register_task
from foreman.state import TransactionBusy, add_assignment, empty_state, save_state, state_lock

AT = "2026-09-23T08:00:00+00:00"


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / "owner.json"
        self.state.write_text("original operational state\n")
        self.path = budget.location(self.state)
        self.packet = {"schema_version": 3, "task": "t", "decision": "gate",
                       "core": {"authority": "operator", "head": "a" * 40,
                                "unknown_deliveries": ["unresolved"], "findings": ["blocking"]},
                       "authorizes_progression": False, "content": "private-report-body"}

    def consume(self, packet=None, digest="a" * 64, identity=None):
        return budget.consume(self.state, packet or self.packet, digest, identity)

    def document(self):
        return json.loads(self.path.read_text())

    def test_exact_printed_bytes_accumulate_across_decisions_questions_and_offsets(self):
        first = self.consume()
        second = self.consume({**self.packet, "decision": "diagnose", "question": "Why?", "offset": 4096})
        first_size = len((json.dumps(first, indent=2) + "\n").encode())
        total = first_size + len((json.dumps(second, indent=2) + "\n").encode())
        self.assertEqual(second["aggregate_budget"]["previously_returned_bytes"], first_size)
        self.assertEqual(self.document()["tasks"]["t"]["returned_bytes"], total)
        self.assertEqual(self.document()["returned_bytes"], total)
        self.assertEqual(self.document()["tasks"]["t"]["responses"], 2)
        self.assertEqual(second["core"], self.packet["core"])
        self.assertFalse(second["authorizes_progression"])
        self.assertEqual(self.state.read_text(), "original operational state\n")

    def test_lost_counter_refuses_instead_of_granting_an_unused_allowance(self):
        self.consume()
        receipt = budget.presence_location(self.state)
        before = receipt.read_bytes()
        self.path.unlink()
        with self.assertRaisesRegex(StateError, "previously created context counter is missing"):
            self.consume()
        self.assertFalse(self.path.exists())
        self.assertEqual(receipt.read_bytes(), before)

    def test_lost_creation_receipt_rebuilds_only_from_existing_charged_state(self):
        self.consume()
        receipt = budget.presence_location(self.state)
        receipt.unlink()
        result = self.consume()
        self.assertGreater(result["aggregate_budget"]["previously_returned_bytes"], 0)
        self.assertTrue(receipt.is_file())
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        self.assertLessEqual(receipt.stat().st_size, budget.PRESENCE_BYTES)

    def test_receipt_failure_preserves_committed_charges_for_retry(self):
        with patch("foreman.decision_budget._remember", side_effect=StateError("Restore receipt storage.", {})):
            with self.assertRaisesRegex(StateError, "Restore receipt storage"):
                self.consume()
        charged = self.document()["returned_bytes"]
        self.assertGreater(charged, 0)
        self.assertFalse(budget.presence_location(self.state).exists())
        result = self.consume()
        self.assertEqual(result["aggregate_budget"]["previously_returned_bytes"], charged)

    def test_unsupported_foreign_oversized_or_linked_creation_receipts_refuse(self):
        self.consume()
        receipt = budget.presence_location(self.state)
        counter_before = self.path.read_bytes()
        valid = json.loads(receipt.read_text())
        for raw in (b"{", b"x" * (budget.PRESENCE_BYTES + 1),
                    json.dumps({**valid, "schema_version": 2}).encode(),
                    json.dumps({**valid, "state_path_sha256": "b" * 64}).encode()):
            receipt.write_bytes(raw)
            with self.assertRaises(StateError):
                self.consume()
            self.assertEqual(receipt.read_bytes(), raw)
            self.assertEqual(self.path.read_bytes(), counter_before)
        other = receipt.with_name("saved-presence.json")
        receipt.rename(other)
        receipt.symlink_to(other)
        with self.assertRaises(StateError):
            self.consume()
        self.assertEqual(self.path.read_bytes(), counter_before)

    def test_repeated_reads_eventually_refuse_without_resetting_or_overwriting_counters(self):
        count = 0
        for _ in range(100):
            before = self.path.read_bytes() if self.path.exists() else None
            try:
                self.consume({**self.packet, "content": "x" * 3500})
            except UsageError as exc:
                self.assertIn("decision_context_budget_exceeded", json.dumps(exc.to_dict()))
                self.assertEqual(self.path.read_bytes(), before)
                break
            count += 1
        else:
            self.fail("Repeated reads escaped the aggregate allowance")
        self.assertGreater(count, 1)
        self.assertLessEqual(self.document()["tasks"]["t"]["returned_bytes"], budget.DECISION_BYTES)

    def test_escaped_output_consumes_actual_printed_bytes(self):
        result = self.consume({**self.packet, "content": "\u0001" * 1000})
        self.assertEqual(self.document()["tasks"]["t"]["returned_bytes"],
                         len((json.dumps(result, indent=2) + "\n").encode()))
        self.assertGreater(self.document()["tasks"]["t"]["returned_bytes"], 6000)

    def test_oversized_single_response_returns_no_content_or_counter_document(self):
        with self.assertRaises(UsageError):
            self.consume({**self.packet, "content": "x" * budget.OUTPUT_BYTES})
        self.assertFalse(self.path.exists())

    def test_changed_owner_facts_replace_one_counter_without_an_archive(self):
        self.consume()
        result = self.consume(digest="b" * 64)
        self.assertEqual(result["aggregate_budget"]["previously_returned_bytes"], 0)
        self.assertEqual(len(self.document()["tasks"]), 1)
        self.assertEqual(self.document()["tasks"]["t"]["responses"], 1)

    def test_a_changed_bound_foreman_identity_replaces_the_document(self):
        self.consume(identity={"kind": "id", "value": "old-session"})
        self.consume({**self.packet, "task": "other"}, identity={"kind": "id", "value": "old-session"})
        result = self.consume(identity={"kind": "id", "value": "new-session"})
        self.assertEqual(result["aggregate_budget"]["previously_returned_bytes"], 0)
        self.assertEqual(set(self.document()["tasks"]), {"t"})

    def test_identity_metadata_changes_do_not_refund_a_native_session(self):
        self.consume(identity={"kind": "id", "value": "same", "cwd": "/first"})
        result = self.consume(identity={"kind": "id", "value": "same", "cwd": "/other"})
        self.assertGreater(result["aggregate_budget"]["foreman_previously_returned_bytes"], 0)

    def test_lost_binding_refuses_and_preserves_a_bound_session_charge(self):
        self.consume(identity={"kind": "id", "value": "same"})
        before = self.path.read_bytes()
        with self.assertRaisesRegex(StateError, "previously bound"):
            self.consume()
        self.assertEqual(self.path.read_bytes(), before)

    def test_first_binding_carries_offline_charges(self):
        self.consume()
        result = self.consume(identity={"kind": "id", "value": "first"})
        self.assertGreater(result["aggregate_budget"]["foreman_previously_returned_bytes"], 0)

    def test_remote_lease_and_policy_metadata_do_not_refund_the_context(self):
        from dataclasses import replace
        from foreman.command_context import RemoteForemanAttestation
        from foreman.supervision import remote_identity
        receipt = RemoteForemanAttestation("controller", "principal", "machine", "remote-session", "workspace",
                                           "pane", "terminal", 1, "0.7.0", "a" * 64)
        first = remote_identity(receipt, self.state.parent, owner_store_path=self.state.parent / "remote.json")
        self.consume(identity=first)
        refreshed = remote_identity(replace(receipt, lease_epoch=2, policy_version="0.8.0", policy_digest="b" * 64),
                                    self.state.parent, owner_store_path=self.state.parent / "remote.json")
        result = self.consume(identity=refreshed)
        self.assertGreater(result["aggregate_budget"]["foreman_previously_returned_bytes"], 0)

    def test_receipt_overhead_preserves_utf8_pagination_and_charges_final_output(self):
        source = self.state.with_name("report.md")
        original = "\U0001f600" * 1024
        source.write_text(original)
        packet = {"schema_version": 3, "decision": "diagnose", "task": "t" * 512,
                  "enrollment": None, "round_start": None, "budget": {"output_bytes": budget.OUTPUT_BYTES},
                  "files": [{"path": str(source)}]}
        question = "\u0001" * 512
        first_chunk = read_evidence(packet, str(source), question)
        first = self.consume(first_chunk)
        self.assertLess(first["evidence"]["bytes"], first_chunk["evidence"]["bytes"])
        self.assertEqual(first["evidence"]["next_offset"], len(first["evidence"]["content"].encode()))
        second = self.consume(read_evidence(packet, str(source), question, first["evidence"]["next_offset"]))
        self.assertEqual(first["evidence"]["content"] + second["evidence"]["content"], original)
        self.assertIsNone(second["evidence"]["next_offset"])
        printed = [len((json.dumps(result, indent=2) + "\n").encode()) for result in (first, second)]
        self.assertLessEqual(max(printed), budget.OUTPUT_BYTES)
        self.assertEqual(self.document()["returned_bytes"], sum(printed))

    def test_storage_is_private_bounded_and_contains_only_current_counters(self):
        self.consume()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertLessEqual(self.path.stat().st_size, budget.STORE_BYTES)
        self.assertNotIn("private-report-body", self.path.read_text())
        self.assertEqual(set(self.document()), {"schema_version", "state_path", "foreman_sha256", "returned_bytes", "tasks"})

    def test_new_task_states_cannot_refund_the_foreman_session_allowance(self):
        for index in range(100):
            before = self.path.read_bytes() if self.path.exists() else None
            try:
                self.consume({**self.packet, "content": "x" * 3500}, digest="{:064x}".format(index))
            except UsageError as exc:
                self.assertIn('"scope": "foreman_session"', json.dumps(exc.to_dict()))
                self.assertEqual(self.path.read_bytes(), before)
                break
        else:
            self.fail("Task-state changes escaped the bound foreman allowance")
        self.assertLessEqual(self.document()["returned_bytes"], budget.FOREMAN_BYTES)
        self.assertEqual(len(self.document()["tasks"]), 1)

    def test_escaped_task_id_storage_refuses_before_exceeding_the_file_bound(self):
        for index in range(budget.MAX_TASKS):
            before = self.path.read_bytes() if self.path.exists() else None
            try:
                self.consume({**self.packet, "task": "{}-".format(index) + "\U0001f600" * 250})
            except UsageError as exc:
                self.assertIn("storage bound", str(exc))
                self.assertEqual(self.path.read_bytes(), before)
                break
        else:
            self.fail("Escaped long task identities did not exercise the storage bound")
        self.assertLessEqual(self.path.stat().st_size, budget.STORE_BYTES)

    def test_invalid_task_or_binding_never_creates_a_counter(self):
        for task, digest in ((None, "a" * 64), ("", "a" * 64), ("t", "invalid"), ("\ud800", "a" * 64)):
            with self.subTest(task=task):
                with self.assertRaises(UsageError):
                    self.consume({**self.packet, "task": task}, digest=digest)
                self.assertFalse(self.path.exists())

    def test_capacity_refuses_new_tasks_without_evicting_spent_allowances(self):
        for index in range(budget.MAX_TASKS):
            self.consume({**self.packet, "task": "task-{}".format(index)})
        before = self.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "task counter capacity"):
            self.consume({**self.packet, "task": "overflow"})
        self.assertEqual(self.path.read_bytes(), before)

    def test_newer_malformed_foreign_or_oversized_documents_are_preserved(self):
        self.consume()
        valid = self.document()
        fixtures = [b"{", b"x" * (budget.STORE_BYTES + 1)]
        for replacement in ({**valid, "schema_version": 2}, {**valid, "state_path": "/other/owner"},
                            {**valid, "tasks": {"\ud800": valid["tasks"]["t"]}}):
            fixtures.append(json.dumps(replacement).encode())
        for raw in fixtures:
            with self.subTest(raw=raw[:40]):
                self.path.write_bytes(raw)
                with self.assertRaises(StateError):
                    self.consume()
                self.assertEqual(self.path.read_bytes(), raw)

    def test_linked_nonprivate_and_nonregular_counter_paths_refuse(self):
        self.consume()
        original = self.path.read_bytes()
        self.path.chmod(0o644)
        with self.assertRaises(StateError):
            self.consume()
        self.path.chmod(0o600)
        other = self.path.with_name("original-context.json")
        self.path.rename(other)
        self.path.symlink_to(other)
        with self.assertRaises(StateError):
            self.consume()
        self.path.unlink()
        os.link(other, self.path)
        with self.assertRaises(StateError):
            self.consume()
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        with self.assertRaises(StateError):
            self.consume()
        self.assertEqual(other.read_bytes(), original)

    def test_counter_lock_prevents_concurrent_debit(self):
        self.consume()
        before = self.path.read_bytes()
        with state_lock(self.path):
            with self.assertRaises(TransactionBusy):
                self.consume()
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_counter_commit_emits_no_success_and_preserves_spent_bytes(self):
        self.consume()
        before = self.path.read_bytes()
        with patch("foreman.decision_budget.save_state", side_effect=StateError("Restore storage.", {})):
            with self.assertRaisesRegex(StateError, "Restore storage"):
                self.consume()
        self.assertEqual(self.path.read_bytes(), before)

    def test_canonical_state_aliases_share_the_same_allowance(self):
        self.consume()
        alias = self.state.with_name("alias.json")
        alias.symlink_to(self.state)
        result = budget.consume(alias, self.packet, "a" * 64, None)
        self.assertGreater(result["aggregate_budget"]["previously_returned_bytes"], 0)
        self.assertFalse(Path(str(alias) + ".context.json").exists())

    def test_new_processes_keep_the_committed_allowance(self):
        program = ("import json,sys; from foreman.decision_budget import consume; "
                   "print(json.dumps(consume(sys.argv[1], json.loads(sys.argv[2]), 'a'*64, None), indent=2))")
        environ = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman")}
        command = [sys.executable, "-c", program, str(self.state), json.dumps(self.packet)]
        first = subprocess.run(command, env=environ, capture_output=True, text=True, check=True)
        second = subprocess.run(command, env=environ, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(second.stdout)["aggregate_budget"]["previously_returned_bytes"], len(first.stdout.encode()))


class GenerationTest(unittest.TestCase):
    def test_derived_event_boundary_does_not_refund_or_remove_unresumed_holds(self):
        state = empty_state()
        hold = {"id": "operator-hold", "resume_condition": "Recorded continuation", "evidence": ["/owner/hold.md"]}
        packet = build(state, {}, {}, set(), "plan", task="t", exists=lambda path: True,
                       supervision_view={"bound": True, "boundary_held": True, "unresumed_holds": [hold]})
        supervision = {"members": []}
        before = budget.generation(state, packet, supervision)
        packet["supervision"]["boundary_held"] = False
        self.assertEqual(budget.generation(state, packet, supervision), before)
        self.assertEqual(packet["supervision"]["unresumed_holds"], [hold])

    def test_unrelated_tasks_and_query_changes_do_not_refresh_allowance_but_head_changes_do(self):
        state = empty_state()
        register_task(state["recovery"], {"task": "t", "base_revision": "a" * 40, "scope": "fix it",
                      "allowed_paths": ["src/*"], "authorization": {"source": "operator", "quote": "go"}}, AT)
        supervision = {"members": [], "binding": None}

        def generation(decision="plan"):
            packet = build(state, {}, {}, set(), decision, task="t", exists=lambda path: True)
            return budget.generation(state, packet, supervision)

        before = generation()
        add_assignment(state, AT, "developer", "grok", task="unrelated")
        self.assertEqual(generation(), before)
        self.assertEqual(generation("diagnose"), before)
        state["recovery"]["tasks"]["t"]["base_revision"] = "b" * 40
        self.assertNotEqual(generation(), before)

    def test_pane_output_and_watcher_heartbeat_do_not_refresh_a_task_allowance(self):
        state = empty_state()
        packet = build(state, {}, {}, set(), "plan", task="t", exists=lambda path: True)
        supervision = {"members": [{"assignment": {"task": "t"}, "observed": {
            "report": {"present": True, "sha256": "a" * 64}, "visible": {"sha256": "a" * 64}}}],
                       "watchers": [{"heartbeat": AT}]}
        before = budget.generation(state, packet, supervision)
        supervision["members"][0]["observed"]["visible"]["sha256"] = "b" * 64
        supervision["watchers"][0]["heartbeat"] = "2026-09-23T08:01:00+00:00"
        self.assertEqual(budget.generation(state, packet, supervision), before)
        supervision["members"][0]["observed"]["report"]["sha256"] = "b" * 64
        self.assertNotEqual(budget.generation(state, packet, supervision), before)


if __name__ == "__main__":
    unittest.main()
