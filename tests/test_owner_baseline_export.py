"""Frozen owner joins retain uncertainty and cannot manufacture acceptance."""

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.coordination_baseline import summarize
from scripts.export_owner_baseline import EvidenceReader, export as export_snapshot, native_times, opaque


READER = EvidenceReader(ROOT)


def export(owner, supervision, start, end, native, assessment):
    return export_snapshot(owner, supervision, start, end, native, assessment, closure=READER.closed)


START = datetime(2026, 10, 10, tzinfo=timezone.utc)
END = datetime(2026, 10, 10, 1, tzinfo=timezone.utc)
IDENTITY = {"source": "herdr:codex", "agent": "codex", "kind": "id", "value": "private-native-session"}


def inputs():
    dispatch = {"id": "private-dispatch", "task": "private-task", "agent": "private-worker",
                "at": "2026-10-10T00:01:00Z", "status": "applied",
                "result": {"context_session": IDENTITY}}
    member = {"id": dispatch["id"], "assignment": {"id": dispatch["id"], "task": dispatch["task"],
              "agent": dispatch["agent"], "report": "/private/worker-report.md", "native_session": None},
              "refinements": [{"at": "2026-10-10T00:02:00Z", "native_session": IDENTITY}],
              "resolution": {"at": "2026-10-10T00:20:00Z", "outcome": "private prose", "evidence": []}}
    owner = {"schema_version": 11, "assignments": [
             {"task": dispatch["task"], "role": "developer", "status": "applied", "at": dispatch["at"]}],
             "recovery": {"schema_version": 18, "dispatches": [dispatch],
             "tasks": {"private-task": {"task": "private-task", "at": dispatch["at"]}},
             "events": [{"sequence": 1, "task": "private-task", "kind": "task_closed", "at": "2026-10-10T00:30:00Z"}]}}
    supervision = {"schema_version": 1, "state_path": "/private/owner-state.json", "members": [member],
                   "events": [{"member": dispatch["id"], "kind": "report_observed", "at": "2026-10-10T00:06:00Z",
                               "data": {"present": True, "size": 120, "path": "/private/worker-report.md"}}],
                   "holds": [{"at": "2026-10-10T00:25:00Z", "resumed_at": None, "kind": "waiting_for_user",
                              "resume_condition": "private instruction", "dispositions": [{"member": dispatch["id"]}]}]}
    return owner, supervision


def native(*_arguments):
    return {"native_started_at": "2026-10-10T00:02:00Z", "native_completed_at": "2026-10-10T00:07:00Z"}


class OwnerExportTest(unittest.TestCase):
    def test_codex_native_turn_timing_ignores_later_bookkeeping(self):
        rows = [{"type": "event_msg", "payload": {"type": "task_started"}, "timestamp": "2026-10-10T00:02:00Z"},
                {"type": "event_msg", "payload": {"type": "task_complete"}, "timestamp": "2026-10-10T00:07:00Z"},
                {"type": "bookkeeping", "timestamp": "2026-10-10T00:59:00Z"}]
        started, completed = native_times(rows, "codex", "fixture", None)
        assert started is not None and completed is not None
        self.assertEqual((completed - started).total_seconds(), 300)
        self.assertEqual(native_times([], "codex", "fixture", None), (None, None))

    def test_grok_native_timestamps_use_seconds_and_ignore_post_turn_hooks(self):
        base = int(START.timestamp())
        rows = [{"timestamp": base + 10, "params": {"update": {"event_name": "user_prompt_submit"}}},
                {"timestamp": base + 40, "params": {"update": {"sessionUpdate": "turn_completed"}}},
                {"timestamp": base + 80, "params": {"update": {"event_name": "stop"}}}]
        started, completed = native_times(rows, "grok", "fixture", None)
        assert started is not None and completed is not None
        self.assertEqual((completed - started).total_seconds(), 30)
        self.assertEqual(started.tzinfo, timezone.utc)

    def test_claude_tool_results_do_not_restart_the_measured_turn(self):
        class ChainReader:
            @staticmethod
            def main_chain(rows, _session):
                return rows

            @staticmethod
            def tool_output(message):
                return message.get("tool_result") is True

        rows = [{"type": "user", "message": {}, "timestamp": "2026-10-10T00:02:00Z"},
                {"type": "user", "message": {"tool_result": True}, "timestamp": "2026-10-10T00:05:00Z"},
                {"type": "assistant", "timestamp": "2026-10-10T00:07:00Z"}]
        started, completed = native_times(rows, "claude", "fixture", ChainReader)
        assert started is not None and completed is not None
        self.assertEqual((completed - started).total_seconds(), 300)

    def test_bound_native_report_and_distinct_owner_latencies_are_preserved(self):
        owner, supervision = inputs()
        result = export(owner, supervision, START, END, native, lambda *_: "2026-10-10T00:12:00Z")
        measured = summarize(result)
        self.assertEqual(measured["latency_seconds"]["native_work"]["median"], 300)
        self.assertEqual(measured["latency_seconds"]["completion_to_assessment"]["median"], 300)
        self.assertEqual(measured["latency_seconds"]["completion_to_resolution"]["median"], 780)
        self.assertEqual(measured["outcomes"]["acceptance"]["evidenced"], 0)
        self.assertEqual(measured["coverage"]["task_states"], {"owner_closed": 1})
        self.assertEqual(measured["effort"]["report_bytes"]["total"], 120)
        self.assertEqual(measured["holds"][0]["reason"], "operator")

    def test_missing_conflicting_or_later_identity_never_supplies_native_timing(self):
        for case in ("missing", "conflicting", "later", "contradictory-enrollment"):
            with self.subTest(case=case):
                owner, supervision = inputs()
                member = supervision["members"][0]
                if case in ("missing", "later"):
                    owner["recovery"]["dispatches"][0]["result"] = {}
                    member["refinements"] = [] if case == "missing" else [
                        {"at": "2026-10-10T02:00:00Z", "native_session": IDENTITY}]
                elif case == "conflicting":
                    member["refinements"] = [{"at": "2026-10-10T00:03:00Z",
                                               "native_session": {**IDENTITY, "value": "another-session"}}]
                else:
                    member["assignment"]["task"] = "another-task"
                if case == "contradictory-enrollment":
                    with self.assertRaises(ValueError):
                        export(owner, supervision, START, END, native, lambda *_: None)
                else:
                    result = export(owner, supervision, START, END, native, lambda *_: None)
                    self.assertEqual(result["assignments"][0]["native_match"], "unknown")
                    self.assertNotIn("native_completed_at", result["assignments"][0])

    def test_unsent_attempts_preserve_task_cohort_but_do_not_become_busy_workers(self):
        owner, supervision = inputs()
        owner["recovery"]["dispatches"].append({"id": "unsent", "task": "unsent-task", "agent": "private-worker",
                                               "at": "2026-10-10T00:02:00Z", "status": "not_sent"})
        owner["recovery"]["dispatches"].append({"id": "uncertain", "task": "uncertain-task", "agent": "private-worker",
                                               "at": "2026-10-10T00:03:00Z", "status": "sent_but_not_started"})
        result = export(owner, supervision, START, END, native, lambda *_: None)
        self.assertEqual(len(result["tasks"]), 3)
        self.assertEqual(len(result["assignments"]), 2)
        self.assertEqual(result["assignments"][1]["native_match"], "unknown")
        unrelated = [task for task in result["tasks"] if task["id"] != opaque("private-task", "task-")]
        self.assertTrue(all(task["holds"] == [] for task in unrelated))

    def test_send_time_crash_retains_an_unknown_envelope_without_native_proof(self):
        owner, supervision = inputs()
        owner["recovery"]["dispatches"].extend([
            {"id": "sending", "task": "sending-task", "agent": "private-worker",
             "at": "2026-10-10T00:03:00Z", "status": "sending"},
            {"id": "reserved", "task": "reserved-task", "agent": "private-worker",
             "at": "2026-10-10T00:04:00Z", "status": "reserved"}])
        result = export(owner, supervision, START, END, native, lambda *_: None)
        self.assertEqual(len(result["tasks"]), 3)
        self.assertEqual(len(result["assignments"]), 2)
        pending = result["assignments"][1]
        self.assertEqual(pending["id"], opaque("sending", "assignment-"))
        self.assertEqual(pending["native_match"], "unknown")
        self.assertNotIn("native_completed_at", pending)
        self.assertEqual(summarize(result)["coverage"]["assignments"], 2)

    def test_closure_uses_owner_chronology_at_the_window_boundary(self):
        for role, status, at, expected in (
                ("developer", "applied", "2026-10-10T00:40:00Z", "owner_open"),
                ("developer", "applied", "2026-10-10T02:00:00Z", "owner_closed"),
                ("reviewer", "applied", "2026-10-10T00:40:00Z", "owner_closed"),
                ("developer", "sent_but_not_started", "2026-10-10T00:40:00Z", "owner_closed")):
            with self.subTest(role=role, status=status, at=at):
                owner, supervision = inputs()
                owner["assignments"].append({"task": "private-task", "role": role, "status": status, "at": at})
                result = export(owner, supervision, START, END, native, lambda *_: None)
                self.assertEqual(result["tasks"][0]["state"], expected)
        owner, supervision = inputs()
        owner["assignments"].append({"task": "private-task", "role": "developer", "status": "applied",
                                     "at": "2026-10-10T00:40:00Z"})
        # Imported events can append out of time order. Latest valid closure
        # wins; an older event at the tail cannot reopen or reclose the task.
        owner["recovery"]["events"].insert(0, {"sequence": 2, "task": "private-task", "kind": "task_closed",
                                              "at": "2026-10-10T00:50:00Z"})
        result = export(owner, supervision, START, END, native, lambda *_: None)
        self.assertEqual(result["tasks"][0]["state"], "owner_closed")

    def test_ambiguous_owner_closure_is_a_setup_error(self):
        owner, supervision = inputs()
        owner["recovery"]["events"].append({**owner["recovery"]["events"][0], "sequence": 2})
        with self.assertRaisesRegex(ValueError, "owner closure chronology is uncertain"):
            export(owner, supervision, START, END, native, lambda *_: None)

    def test_archived_observation_is_only_a_candidate_until_native_report_proof_matches(self):
        owner, supervision = inputs()
        owner["recovery"]["dispatches"][0]["result"] = {}
        member = supervision["members"][0]
        member.update(active=False, refinements=[], observed={"identity": {"pane_id": "fixture-pane", "native_session": IDENTITY}})
        result = export(owner, supervision, START, END, native, lambda *_: None)
        self.assertEqual(result["assignments"][0]["native_match"], "matched")
        result = export(owner, supervision, START, END, lambda *_: {}, lambda *_: None)
        self.assertEqual(result["assignments"][0]["native_match"], "unknown")
        for mutation in (lambda m: m.update(active=True),
                         lambda m: m["resolution"].update(at="2026-10-10T02:00:00Z"),
                         lambda m: m["assignment"].update(pane_id="different-pane"),
                         lambda m: m["observed"].update(identity_changed={"pane_id": "fixture-pane"})):
            candidate = copy.deepcopy(member)
            mutation(candidate)
            data = {**supervision, "members": [candidate]}
            result = export(owner, data, START, END, native, lambda *_: None)
            self.assertEqual(result["assignments"][0]["native_match"], "unknown")

    def test_future_resolution_reports_and_closure_do_not_leak_into_the_window(self):
        owner, supervision = inputs()
        owner["recovery"]["events"][0]["at"] = "2026-10-10T02:00:00Z"
        supervision["members"][0]["resolution"]["at"] = "2026-10-10T02:00:00Z"
        supervision["events"][0]["at"] = "2026-10-10T02:00:00Z"
        result = export(owner, supervision, START, END, lambda *_: {}, lambda *_: None)
        self.assertNotIn("resolved_at", result["assignments"][0])
        self.assertNotIn("report_bytes", result["assignments"][0])
        self.assertEqual(result["tasks"][0]["state"], "owner_open")

    def test_unknown_schema_or_duplicate_enrollment_is_a_setup_error(self):
        owner, supervision = inputs()
        for field in ("owner", "supervision", "recovery", "duplicate", "boolean-version", "float-version"):
            a, b = copy.deepcopy(owner), copy.deepcopy(supervision)
            if field == "owner":
                a["schema_version"] = 999
            elif field == "supervision":
                b["schema_version"] = 999
            elif field == "recovery":
                a["recovery"]["schema_version"] = 999
            elif field == "boolean-version":
                b["schema_version"] = True
            elif field == "float-version":
                a["schema_version"] = 11.0
            else:
                b["members"].append(copy.deepcopy(b["members"][0]))
            with self.subTest(field=field), self.assertRaises(ValueError):
                export(a, b, START, END, native, lambda *_: None)

    def test_export_projects_away_private_paths_ids_prose_and_unexpected_probe_fields(self):
        owner, supervision = inputs()
        result = export(owner, supervision, START, END,
                        lambda *_: {**native(), "raw_transcript": "private transcript"}, lambda *_: None)
        serialized = json.dumps(result)
        for marker in ("private", "worker-report", "native-session", "resume_condition", "raw_transcript"):
            self.assertNotIn(marker, serialized)
        measured = summarize(result)
        self.assertEqual(measured["effort"]["foreman"]["output_bytes"]["unknown"], 1)
        self.assertEqual(measured["coverage"]["class_risk_mix"], {"unknown/unknown": 1})


if __name__ == "__main__":
    unittest.main()
