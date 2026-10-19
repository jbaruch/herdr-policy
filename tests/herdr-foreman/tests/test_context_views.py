"""Large current/history fixtures cannot become unbounded foreman tool output."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import hashlib
import io
import json
import unittest
from argparse import Namespace
from unittest.mock import Mock, patch

from foreman import attention, context_output, memory, supervision as store
from foreman import supervision_runtime as runtime
from foreman.cli import cmd_foreman_reset
from foreman.errors import UsageError
from foreman.state import empty_state, save_state
from tests.test_attention import obligation
from tests.test_cli import CliCase
from tests.test_foreman_queue import register

AT = "2026-09-01T12:00:00+00:00"


class ContextViewsTest(CliCase):
    def setUp(self):
        super().setUp()
        self.source = self.state.parent / "context-evidence.md"
        self.source.write_text("Keep the unresolved source evidence.\n")
        self.capture = {"id": "handoff", "capture": "Continue the saved goal at the selected task.",
                        "unresolved_work": ["Keep the unanswered operator decision on task t."],
                        "gaps": [{"missing": "The operator's decision", "task": "t",
                                  "recovery": {"ask": "Which of the recorded options is authorized?"}}],
                        "required_reads": [str(self.source)]}
        self.lesson = {"id": "lesson-0", "lesson_id": "one-lesson", "supersedes": None, "status": "active",
                       "lesson": "Use current evidence. " + "x" * 1200, "scopes": ["task:t"],
                       "sources": [str(self.source)], "last_verified_at": AT, "expires_at": None,
                       "revalidate_when": "The selected head changes.", "reason": "Retain the observed correction."}

    def output(self, arguments):
        self.out, self.err = io.StringIO(), io.StringIO()
        code, out, err = self.run_cli(self.base() + arguments)
        self.assertEqual(code, 0, err)
        self.assertLessEqual(len(out.encode()), context_output.OUTPUT_BYTES)
        result = json.loads(out)
        self.assertEqual(result["schema_version"], context_output.VIEW_SCHEMA_VERSION)
        self.assertFalse(result["authorizes_progression"])
        return result, out

    def bind(self):
        who = store.identity("context-fixture", str(self.state.parent), "fixture", pane_id="fixture-pane")
        store.bind(self.state, who, AT, root=self.state.parent / "fixture-bindings")

    def events(self, count):
        def append(data):
            for _ in range(count):
                store.append_event(data, AT, None, "unknown_observed", {"private_detail": "Ω" * 1000})
        store.transaction(self.state, append)

    def test_queue_pages_long_task_ids_without_losing_or_mutating_tasks(self):
        state = empty_state()
        names = ["task-{:03}-{}".format(index, "q" * 180) for index in range(90)]
        for name in names:
            register(state, name)
        save_state(self.state, state)
        before = self.state.read_bytes()
        offset, seen = 0, []
        while offset is not None:
            view, _ = self.output(["foreman-queue", "--limit", "50", "--offset", str(offset)])
            seen.extend(row["task"] for row in view["queue"])
            self.assertEqual(view["pagination"]["total"], len(names))
            self.assertEqual(view["pagination"]["offset"], offset)
            offset = view["pagination"]["next_offset"]
        self.assertEqual(seen, names)
        self.assertEqual(self.state.read_bytes(), before)

    def test_catch_up_keeps_unshown_blocker_in_the_native_dispatch_gate(self):
        for index in range(16):
            data = {**obligation("question-{:02}".format(index)), "context": "Ω" * 500}
            attention.write(self.state, "record", data, AT)
        attention.write(self.state, "record", obligation("last-blocker", kind="blocker", priority=1), AT)
        before = attention.storage_path(self.state).read_bytes()
        first, _ = self.output(["catch-up", "--compact", "--limit", "50", "--now", AT])
        self.assertLess(first["attention"]["returned"], first["attention"]["total"])
        self.assertFalse(first["context_complete"])
        self.assertNotIn("markdown", first)
        self.assertNotIn("sources", first)
        self.assertNotIn("last-blocker", [row["id"] for row in first["attention"]["items"]])
        self.assertIn("last-blocker", [row["id"] for row in attention.dispatch_gate(self.state, "owner/repo#5", AT)])
        seen, offset = [], 0
        while offset is not None:
            page, _ = self.output(["catch-up", "--compact", "--limit", "50", "--offset", str(offset), "--now", AT])
            seen.extend(row["id"] for row in page["attention"]["items"])
            offset = page["attention"]["next_offset"]
        self.assertEqual(len(seen), 17)
        self.assertEqual(len(set(seen)), 17)
        self.assertIn("last-blocker", seen)
        self.assertEqual(attention.storage_path(self.state).read_bytes(), before)

    def test_indivisible_giant_thread_refuses_without_hiding_or_resolving_it(self):
        data = {**obligation("large-blocker", kind="blocker"), "context": "雪" * 7000}
        attention.write(self.state, "record", data, AT)
        before = attention.storage_path(self.state).read_bytes()
        code, out, err = self.run_cli(self.base() + ["catch-up", "--compact", "--now", AT])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("context_budget_exceeded", err)
        self.assertLess(len(err.encode()), context_output.OUTPUT_BYTES)
        self.assertEqual(attention.storage_path(self.state).read_bytes(), before)
        self.assertEqual([row["id"] for row in attention.dispatch_gate(self.state, "owner/repo#5", AT)], ["large-blocker"])

    def test_current_memory_does_not_replay_revision_history(self):
        previous = None
        for index in range(35):
            data = {**self.lesson, "id": "lesson-{}".format(index), "supersedes": previous}
            memory.record(self.state, data, AT)
            previous = data["id"]
        before = memory.location(self.state).read_bytes()
        current, _ = self.output(["memory-show", "--id", previous, "--now", AT])
        self.assertEqual(current["record"]["id"], previous)
        self.assertEqual(current["history_count"], 35)
        self.assertFalse(current["history_included"])
        self.assertEqual(current["history"], [])
        offset, seen = 0, []
        while offset is not None:
            view, _ = self.output(["memory-show", "--id", previous, "--history", "--limit", "50",
                                   "--offset", str(offset), "--now", AT])
            seen.extend(row["id"] for row in view["history"])
            offset = view["history_pagination"]["next_offset"]
        self.assertEqual(seen, ["lesson-{}".format(index) for index in range(35)])
        self.assertEqual(memory.location(self.state).read_bytes(), before)

    def test_new_oversized_handoff_is_rejected_before_commit(self):
        memory.stow(self.state, self.capture, AT)
        before = memory.location(self.state).read_bytes()
        with self.assertRaises(UsageError):
            memory.stow(self.state, {**self.capture, "id": "too-large", "capture": "雪" * 20_000}, AT)
        self.assertEqual(memory.location(self.state).read_bytes(), before)
        current, _ = self.output(["memory-show", "--now", AT])
        self.assertEqual(current["record"]["gaps"], self.capture["gaps"])
        self.assertEqual(current["record"]["unresolved_work"], self.capture["unresolved_work"])

    def test_lesson_pages_retain_every_applicable_current_record(self):
        for index in range(24):
            memory.record(self.state, {**self.lesson, "id": "current-{}".format(index),
                                       "lesson_id": "separate-{}".format(index)}, AT)
        before = memory.location(self.state).read_bytes()
        offset, seen = 0, []
        while offset is not None:
            view, _ = self.output(["memory-list", "--scope", "task:t", "--limit", "50", "--offset", str(offset), "--now", AT])
            seen.extend(row["id"] for row in view["lessons"])
            offset = view["pagination"]["next_offset"]
        self.assertEqual(seen, ["current-{}".format(index) for index in range(24)])
        self.assertEqual(memory.location(self.state).read_bytes(), before)

    def test_legacy_oversized_handoff_is_preserved_and_refuses_readiness(self):
        memory.stow(self.state, self.capture, AT)
        document = json.loads(memory.location(self.state).read_text())
        document["records"][0]["capture"] = "Earlier oversized capture. " * 10_000
        memory.location(self.state).write_text(json.dumps(document))
        before = memory.location(self.state).read_bytes()
        with self.assertRaises(UsageError):
            memory.show(self.state, AT)
        spawn = Mock(side_effect=AssertionError("An unreadable handoff cannot start a reset child."))
        with patch("foreman.cli.supervision.load", side_effect=AssertionError("Refuse before reading supervision.")):
            with self.assertRaises(UsageError):
                cmd_foreman_reset(Namespace(state=str(self.state), now=AT, stow="handoff"), spawn=spawn)
        spawn.assert_not_called()
        self.assertEqual(memory.location(self.state).read_bytes(), before)

    def test_large_source_is_a_verified_reference_without_its_body_in_context(self):
        body = ("private source bytes Ω\n" * 150_000).encode()
        self.source.write_bytes(body)
        memory.stow(self.state, self.capture, AT)
        view, out = self.output(["memory-show", "--now", AT])
        receipt = view["record"]["required_reads"][0]
        self.assertEqual(receipt["size"], len(body))
        self.assertEqual(receipt["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(receipt["observation"], "same_bytes")
        self.assertNotIn("private source bytes", out)

    def test_event_sequence_cursor_survives_ack_and_keeps_snapshot_boundary(self):
        self.bind()
        self.events(17)
        first, _ = self.output(["supervision-drain", "--compact", "--limit", "3"])
        self.assertEqual([row["seq"] for row in first["events"]], [1, 2, 3])
        self.assertEqual(first["event_page"]["next_after"], 3)
        self.assertTrue(all(row["data_included"] is False for row in first["events"]))
        gate, _ = self.output(["supervision-gate", "--limit", "3"])
        self.assertEqual(gate["counts"]["pending"], 17)
        self.assertEqual({row["event"] for row in gate["wake"]}, {row["id"] for row in first["events"]})
        record = self.state.parent / "ack.json"
        record.write_text(json.dumps({"through": first["through"], "outcomes": [
            {"event": row["id"], "outcome": "Fixture inspected the named event.", "evidence": [str(self.source)]}
            for row in first["events"]]}))
        acknowledged, _ = self.output(["supervision-ack", "--compact", "--record", str(record), "--now", AT])
        self.assertEqual(acknowledged["remaining_count"], 14)
        self.assertFalse(acknowledged["pending_included"])
        self.events(1)
        next_page, _ = self.output(["supervision-drain", "--compact", "--limit", "3", "--after", "3", "--through", "17"])
        self.assertEqual([row["seq"] for row in next_page["events"]], [4, 5, 6])
        self.assertEqual(next_page["event_page"]["earlier_pending"], 0)
        self.assertIn(18, [row["seq"] for row in store.pending(store.load(self.state))])

    def test_cursor_cannot_make_earlier_unhandled_events_disappear(self):
        self.bind()
        self.events(17)
        view, _ = self.output(["supervision-drain", "--compact", "--after", "17"])
        self.assertEqual(view["events"], [])
        self.assertEqual(view["event_page"]["earlier_pending"], 17)
        self.assertFalse(view["context_complete"])
        self.assertEqual(len(store.pending(store.load(self.state))), 17)

    def test_invalid_watch_view_options_refuse_before_starting_a_watch(self):
        self.bind()
        before = store.store_path(self.state).read_bytes()
        for limit, after in ((0, 0), (10, 1)):
            args = Namespace(command="supervision-watch", now=AT, limit=limit, after=after,
                             compact=True, duration=1, interval=1)
            with patch.object(runtime, "watch", side_effect=AssertionError("Invalid options cannot start a watch.")) as watch:
                with self.assertRaises(UsageError):
                    runtime.run_command(args, self.state, AT, client=object(), clock=lambda: AT, sleeper=lambda _s: None)
                watch.assert_not_called()
        self.assertEqual(store.store_path(self.state).read_bytes(), before)

    def test_late_hold_refuses_resume_without_clearing_either_hold(self):
        self.bind()
        for identifier in ("inspected", "arrived-later"):
            store.hold(self.state, {"id": identifier, "kind": "waiting_for_user",
                                   "resume_condition": "The operator must supply this decision.",
                                   "evidence": [str(self.source)], "dispositions": []}, AT)
        before = store.store_path(self.state).read_bytes()
        code, out, err = self.run_cli(self.base() + ["supervision-resume", "--compact", "--hold", "inspected", "--now", AT])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("holds_changed", err)
        self.assertEqual(store.store_path(self.state).read_bytes(), before)
        view, _ = self.output(["supervision-status", "--compact", "--now", AT])
        self.assertEqual({row["id"] for row in view["unresumed_holds"]}, {"inspected", "arrived-later"})
        resumed, _ = self.output(["supervision-resume", "--compact", "--hold", "inspected", "--hold", "arrived-later", "--now", AT])
        self.assertTrue(resumed["resumed"])
        self.assertTrue(all(row["resumed_at"] is not None for row in store.load(self.state)["holds"]))

    def test_compact_supervision_keeps_holds_and_omits_large_observation_bodies(self):
        self.bind()
        members = []
        for index in range(60):
            identifier = "member-{}".format(index)
            store.enroll(self.state, {"id": identifier, "agent": identifier, "task": "task-{}".format(index),
                                     "report": str(self.source), "pane_id": None, "native_session": None}, AT)
            members.append(identifier)
        store.hold(self.state, {"id": "operator-hold", "kind": "waiting_for_user",
                               "resume_condition": "The operator must supply the saved decision.",
                               "evidence": [str(self.source)], "dispositions": [
                                   {"member": member, "outcome": "Keep this assignment covered.", "evidence": [str(self.source)]}
                                   for member in members]}, AT)
        def observe(data):
            for row in data["members"]:
                row["observed"]["unknown_tool"] = {"private_detail": "never replay this body " * 10_000}
        store.transaction(self.state, observe)
        before = store.store_path(self.state).read_bytes()
        view, out = self.output(["supervision-status", "--compact", "--now", AT])
        self.assertEqual(view["active_page"]["total"], 60)
        self.assertFalse(view["observation_details_included"])
        self.assertEqual(view["unresumed_holds"][0]["id"], "operator-hold")
        self.assertEqual(view["unresumed_holds"][0]["disposition_count"], 60)
        self.assertFalse(view["unresumed_holds"][0]["dispositions_included"])
        self.assertNotIn("dispositions", view["unresumed_holds"][0])
        self.assertNotIn("never replay this body", out)
        self.assertEqual(store.store_path(self.state).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
