"""Each foreman decision loads the owner-linked records it depends on (#483)."""

import sys as _test_sys
from pathlib import Path as _TestPath
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str((Path(__file__).resolve().parents[3] / "skills/herdr-foreman")))

from foreman.errors import StateError, UsageError
from foreman.load_set import OUTPUT_BYTES, READ_BYTES, build, read_evidence
from foreman.recovery import register_task
from foreman.state import add_assignment, empty_state, save_state
from tests.test_cli import CliCase

DEV_0 = "2026-09-23T08:00:00+00:00"
REVIEW_0 = "2026-09-23T08:30:00+00:00"
DEV_1 = "2026-09-23T09:00:00+00:00"
REVIEW_1 = "2026-09-23T09:30:00+00:00"
TEST_1 = "2026-09-23T09:40:00+00:00"


def dispatch(state, at, role, agent, task="t", fix_round=None, **extra):
    add_assignment(state, at, role, agent, task=task, fix_round=fix_round)
    identifier = "{}-{}:{}".format(task, len(state["assignments"]), role)
    state["recovery"]["dispatches"].append({"id": identifier, "task": task, "role": role, "agent": agent,
                                            "status": "applied", "assignment_index": len(state["assignments"]) - 1,
                                            "brief": "/r/{}.brief.md".format(identifier), "common": "/r/COMMON.md",
                                            "report": None, **extra})
    return identifier


def two_rounds():
    state = empty_state()
    register_task(state["recovery"], {"task": "t", "base_revision": "a" * 40, "scope": "fix it", "allowed_paths": ["src/*"],
                                      "authorization": {"source": "operator", "quote": "go"}}, DEV_0)
    ids = {"dev0": dispatch(state, DEV_0, "developer", "grok"),
           "rev0": dispatch(state, REVIEW_0, "reviewer", "claude"),
           "dev1": dispatch(state, DEV_1, "developer", "grok", fix_round=1),
           "rev1": dispatch(state, REVIEW_1, "reviewer", "claude"),
           "test1": dispatch(state, TEST_1, "tester", "codex")}
    state["recovery"]["dispatches"][0]["report"] = {"verdict": "blocking", "head_revision": "b" * 40,
                                                    "report": "/r/review-blocking.md"}
    return state, ids


def reports(ids):
    return {identifier: "/r/{}.report.md".format(identifier) for identifier in ids.values()}


def paths(result):
    return [row["path"] for row in result["files"]]


def run(state, ids, decision, **target):
    return build(state, reports(ids), {}, set(), decision, exists=lambda path: path != "/r/missing.md", **target)


class DecisionTest(unittest.TestCase):
    def test_gate_loads_every_brief_and_report_of_the_current_round_only(self):
        state, ids = two_rounds()
        result = run(state, ids, "gate", task="t")
        self.assertEqual(result["round_start"], DEV_1)
        for key in ("dev1", "rev1", "test1"):
            self.assertIn("/r/{}.brief.md".format(ids[key]), paths(result))
            self.assertIn("/r/{}.report.md".format(ids[key]), paths(result))
        self.assertNotIn("/r/{}.report.md".format(ids["rev0"]), paths(result))
        self.assertEqual(paths(result).count("/r/COMMON.md"), 1)

    def test_brief_loads_this_rounds_reports_and_every_blocking_receipt(self):
        state, ids = two_rounds()
        result = run(state, ids, "brief", task="t")
        self.assertIn("/r/review-blocking.md", paths(result))
        self.assertIn("/r/{}.report.md".format(ids["rev1"]), paths(result))
        self.assertIn("/r/{}.brief.md".format(ids["dev1"]), paths(result))
        self.assertIn("/r/{}.brief.md".format(ids["rev1"]), paths(result))
        self.assertIn("correction_plan", result["records"])

    def test_diagnose_selects_current_round_and_preserves_unsuperseded_blockers(self):
        state, ids = two_rounds()
        result = run(state, ids, "diagnose", task="t")
        for key in ("dev1", "rev1", "test1"):
            self.assertIn("/r/{}.report.md".format(ids[key]), paths(result))
        for key in ("dev0", "rev0"):
            self.assertNotIn("/r/{}.report.md".format(ids[key]), paths(result))
        self.assertIn("/r/review-blocking.md", paths(result))
        self.assertEqual(set(result["records"]), {"assessments", "checkpoints", "diagnoses", "approaches", "plans",
                                                   "historical_attempts"})

    def imported(self, state, at, verdict):
        add_assignment(state, at, "developer", "grok", task="t", fix_round=2)
        attempt = {"id": "manual-2", "task": "t", "assignment_index": len(state["assignments"]) - 1,
                   "receipts": {"report": {"path": "/r/manual-2.md", "sha256": "0" * 64}},
                   "reviews": [{"input": {"verdict": verdict, "head_revision": "d" * 40, "report": "/r/manual-2-review.md"}}]}
        state["recovery"]["historical_attempts"].append(attempt)
        return attempt

    def test_an_imported_current_round_is_gated_and_diagnosed(self):
        state, ids = two_rounds()
        attempt = self.imported(state, "2026-09-23T10:00:00+00:00", "blocking")
        gate = run(state, ids, "gate", task="t")
        self.assertEqual(gate["records"]["historical_attempts"], [attempt])
        self.assertIn("/r/manual-2.md", paths(gate))
        self.assertIn("/r/manual-2-review.md", paths(gate))
        self.assertNotIn("/r/{}.report.md".format(ids["rev1"]), paths(gate))
        self.assertIn("/r/manual-2-review.md", paths(run(state, ids, "brief", task="t")))
        self.assertIn("/r/manual-2.md", paths(run(state, ids, "diagnose", task="t")))

    def test_an_unknown_send_outcome_refuses_round_decisions(self):
        state, ids = two_rounds()
        state["recovery"]["dispatches"][-1]["status"] = "sent_but_not_started"
        for decision in ("brief", "gate", "diagnose"):
            with self.subTest(decision=decision), self.assertRaisesRegex(UsageError, "unknown send outcome: " + ids["test1"]):
                run(state, ids, decision, task="t")
        self.assertIsNotNone(run(state, ids, "plan", task="t"))

    def test_a_dispatch_without_an_enrollment_refuses_round_decisions(self):
        state, ids = two_rounds()
        paths_by_id = reports(ids)
        del paths_by_id[ids["rev1"]]
        for decision in ("brief", "gate", "diagnose"):
            with self.subTest(decision=decision), self.assertRaisesRegex(UsageError, "no supervision enrollment"):
                build(state, paths_by_id, {}, set(), decision, task="t", exists=lambda path: True)

    def test_a_spent_correction_plan_is_not_offered(self):
        state, ids = two_rounds()
        plan = {"id": "p1", "task": "t", "first_fix": 1, "last_fix": 1, "supersedes": None}
        state["recovery"]["plans"].append(plan)
        self.assertIsNone(run(state, ids, "brief", task="t")["records"]["correction_plan"])
        plan["last_fix"] = 2
        self.assertEqual(run(state, ids, "brief", task="t")["records"]["correction_plan"], plan)

    def test_diagnose_excludes_superseded_receipts_and_retains_current_assessment(self):
        state, ids = two_rounds()
        state["recovery"]["events"].append({"sequence": 1, "kind": "review_superseded", "task": "t", "at": REVIEW_1,
                                            "details": {"previous": {"verdict": "approved", "head_revision": "c" * 40,
                                                                     "report": "/r/superseded.md"}}})
        assessment = {"task": "t", "role": "investigator", "report": "/r/investigation.md", "outcome": "accepted",
                      "summary": "Loop stalls on flaky fixture."}
        state["specialist_assessments"].append(assessment)
        result = run(state, ids, "diagnose", task="t")
        self.assertNotIn("/r/superseded.md", paths(result))
        self.assertIn("/r/investigation.md", paths(result))
        self.assertEqual(result["records"]["assessments"], [assessment])

    def test_archived_reviews_and_unrelated_tasks_do_not_expand_current_context(self):
        state, ids = two_rounds()
        before = run(state, ids, "diagnose", task="t")
        for number in range(2_000):
            state["recovery"]["events"].append({"sequence": number + 1, "kind": "review_superseded", "task": "t", "at": REVIEW_0,
                                                "details": {"previous": {"verdict": "approved", "head_revision": "c" * 40,
                                                                         "report": "/archive/{}.md".format(number)}}})
        dispatch(state, REVIEW_1, "reviewer", "other", task="unrelated")
        self.assertEqual(run(state, ids, "diagnose", task="t"), before)
        unrelated_updates = {str(number): {"id": str(number), "kind": "update", "status": "open", "task": None,
                                          "title": "Unrelated historical notification"} for number in range(2_000)}
        self.assertEqual(build(state, reports(ids), unrelated_updates, set(), "diagnose", task="t", exists=lambda path: True),
                         before)

    def test_oversized_open_obligations_refuse_instead_of_disappearing(self):
        state, ids = two_rounds()
        entries = {"held": {"id": "held", "kind": "blocker", "status": "open", "task": "t", "title": "x" * OUTPUT_BYTES}}
        with self.assertRaises(UsageError) as error:
            build(state, reports(ids), entries, set(), "gate", task="t", exists=lambda path: True)
        diagnostic = json.dumps(error.exception.to_dict())
        self.assertLess(len(diagnostic.encode()), 1_024)
        self.assertIn("context_budget_exceeded", diagnostic)

    def test_evidence_is_question_bound_and_has_explicit_byte_continuations(self):
        state, ids = two_rounds()
        with tempfile.TemporaryDirectory() as scratch:
            report = Path(scratch) / "report.md"
            report.write_bytes(b"a" * READ_BYTES + b"tail123")
            packet = build(state, {**reports(ids), ids["rev1"]: str(report)}, {}, set(), "gate", task="t", exists=lambda path: True)
            first = read_evidence(packet, str(report), "Which verification failed?")
            self.assertEqual((first["evidence"]["bytes"], first["evidence"]["next_offset"]), (READ_BYTES, READ_BYTES))
            self.assertTrue(first["evidence"]["excerpt"])
            self.assertFalse(first["authorizes_progression"])
            self.assertLessEqual(len((json.dumps(first, indent=2) + "\n").encode()), OUTPUT_BYTES)
            tail = read_evidence(packet, str(report), "What remains unread?", READ_BYTES)
            self.assertEqual((tail["evidence"]["content"], tail["evidence"]["next_offset"]), ("tail123", None))
            for target, question in ((str(report), ""), (str(report), "\udcff"),
                                     (str(Path(scratch) / "unlisted"), "Why?")):
                with self.subTest(target=target), self.assertRaises(UsageError):
                    read_evidence(packet, target, question)
            report.unlink()
            with self.assertRaises(StateError):
                read_evidence(packet, str(report), "Is the required evidence available?")

    def test_utf8_chunks_preserve_split_characters_and_refuse_invalid_offsets_or_bytes(self):
        state, ids = two_rounds()
        with tempfile.TemporaryDirectory() as scratch:
            report = Path(scratch) / "utf8.md"
            original = "a" * (READ_BYTES - 1) + "界tail"
            report.write_text(original, encoding="utf-8")
            packet = build(state, {**reports(ids), ids["rev1"]: str(report)}, {}, set(), "gate", task="t", exists=lambda path: True)
            first = read_evidence(packet, str(report), "Read the full original text")
            self.assertEqual(first["evidence"]["next_offset"], READ_BYTES - 1)
            tail = read_evidence(packet, str(report), "Read the continuation", first["evidence"]["next_offset"])
            self.assertEqual(first["evidence"]["content"] + tail["evidence"]["content"], original)
            with self.assertRaisesRegex(UsageError, "character boundary"):
                read_evidence(packet, str(report), "Read an invalid offset", READ_BYTES)
            for body in (b"invalid\xff", b"truncated\xe7\x95"):
                report.write_bytes(body)
                with self.assertRaisesRegex(UsageError, "valid UTF-8"):
                    read_evidence(packet, str(report), "Read valid original evidence")

    def test_evidence_chunk_does_not_repeat_a_near_limit_decision_packet(self):
        state, ids = two_rounds()
        with tempfile.TemporaryDirectory() as scratch:
            report = Path(scratch) / "report.md"
            report.write_bytes(b"x" * (READ_BYTES + 100))
            packet = build(state, {**reports(ids), ids["rev1"]: str(report)}, {}, set(), "gate", task="t", exists=lambda path: True)
            packet["large_current_obligation"] = "x" * (OUTPUT_BYTES - len(json.dumps(packet, indent=2).encode()) - 200)
            self.assertLess(len((json.dumps(packet, indent=2) + "\n").encode()), OUTPUT_BYTES)
            result = read_evidence(packet, str(report), "Inspect this report")
            self.assertEqual(result["kind"], "evidence_chunk")
            self.assertFalse(result["decision_context_included"])
            self.assertFalse(result["authorizes_progression"])
            self.assertEqual(result["evidence"]["bytes"], READ_BYTES)
            self.assertEqual(result["task"], packet["task"])
            self.assertLess(len((json.dumps(result, indent=2) + "\n").encode()), OUTPUT_BYTES)

    def test_plan_names_the_queue_entry_and_the_reserved_developer(self):
        state = empty_state()
        dispatch(state, DEV_0, "developer", "grok")
        result = build(state, {}, {}, set(), "plan", task="t", exists=lambda path: True)
        self.assertEqual(result["records"]["queue"]["waiting_for"], ["reviewer", "tester"])
        self.assertEqual(result["records"]["reserved_developer"], ["grok"])

    def test_wake_is_keyed_by_enrollment(self):
        state, ids = two_rounds()
        result = run(state, ids, "wake", enrollment=ids["rev1"])
        self.assertEqual(result["task"], "t")
        self.assertEqual(paths(result), ["/r/{}.brief.md".format(ids["rev1"]), "/r/COMMON.md",
                                         "/r/{}.report.md".format(ids["rev1"])])

    def test_a_missing_report_is_listed_not_dropped(self):
        state, ids = two_rounds()
        result = build(state, {**reports(ids), ids["rev1"]: "/r/missing.md"}, {}, set(), "gate", task="t",
                       exists=lambda path: path != "/r/missing.md")
        self.assertIn({"path": "/r/missing.md", "why": "report for reviewer " + ids["rev1"], "present": False},
                      result["files"])

    def test_core_carries_open_attention_for_the_task_only(self):
        state, ids = two_rounds()
        entries = {"q": {"id": "q", "kind": "question", "title": "Advisory?", "status": "open", "task": "t"},
                   "done": {"id": "done", "kind": "question", "title": "x", "status": "resolved", "task": "t"},
                   "other": {"id": "other", "kind": "blocker", "title": "y", "status": "open", "task": "u"}}
        result = build(state, reports(ids), entries, set(), "gate", task="t", exists=lambda path: True)
        self.assertEqual(result["core"]["attention"], [entries["q"]])
        self.assertEqual(result["core"]["task"]["scope"], "fix it")

    def test_global_holds_and_unknown_verifier_delivery_survive_a_planning_view(self):
        state, ids = two_rounds()
        state["recovery"]["dispatches"][-1]["status"] = "sent_but_not_started"
        hold = {"id": "operator-stop", "kind": "blocker", "title": "Preserve the global hold", "status": "open", "task": None}
        result = build(state, reports(ids), {"hold": hold}, set(), "plan", task="t", exists=lambda path: True)
        self.assertEqual(result["core"]["attention"], [hold])
        self.assertEqual(result["core"]["unknown_dispatches"], [{"id": ids["test1"], "role": "tester", "status": "sent_but_not_started"}])
        self.assertFalse(result["authorizes_progression"])


class LoadSetCommandTest(CliCase):
    def test_nonregular_evidence_refuses_without_waiting_for_a_fifo_writer(self):
        fifo = self.tmp / "report.fifo"
        os.mkfifo(fifo, 0o600)
        unrelated = self.tmp / "unrelated.txt"
        unrelated.write_text("unrelated fixture must not enter decision context")
        linked = self.tmp / "linked-report.md"
        linked.symlink_to(unrelated)
        program = '''import json,sys
from foreman.load_set import read_evidence
from foreman.errors import StateError
path=sys.argv[1]
packet={"files":[{"path":path}]}
try:
    read_evidence(packet,path,"What evidence is available?")
except StateError as exc:
    print(json.dumps(exc.to_dict()))
else:
    raise RuntimeError("Nonregular evidence returned content")
'''
        environ = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman")}
        for path in (fifo, self.tmp, linked):
            result = subprocess.run([sys.executable, "-c", program, str(path)], env=environ,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["error"], "state_error")
            self.assertNotIn("unrelated fixture", result.stdout)

    def test_cli_retains_the_actual_supervision_hold_as_an_observation(self):
        from foreman import supervision
        state = empty_state()
        register_task(state["recovery"], {"task": "t", "base_revision": "a" * 40, "scope": "fix it",
                                          "allowed_paths": ["src/*"], "authorization": {"source": "operator", "quote": "go"}}, DEV_0)
        save_state(self.state, state)
        evidence = self.tmp / "hold.md"
        evidence.write_text("Await the operator's recorded continuation.\n")
        identity = supervision.identity("fixture-owner", str(self.tmp), "fixture-team", pane_id="fixture-pane")
        supervision.bind(self.state, identity, DEV_0, root=self.tmp / "bindings")
        supervision.hold(self.state, {"id": "operator-stop", "kind": "waiting_for_user", "resume_condition": "Explicit continuation",
                                     "evidence": [str(evidence)], "dispositions": []}, DEV_0)
        code, out, err = self.run_cli(self.base() + ["load-set", "--decision", "plan", "--task", "t"])
        self.assertEqual(code, 0, err)
        view = json.loads(out)["supervision"]
        self.assertTrue(view["boundary_held"])
        self.assertTrue(view["observation_only"])
        self.assertEqual(view["unresumed_holds"][0]["id"], "operator-stop")

    def test_wake_needs_an_enrollment_and_the_rest_need_a_task(self):
        save_state(self.state, empty_state())
        for argv in (["--decision", "wake", "--task", "t"], ["--decision", "gate", "--enrollment", "e"]):
            with self.subTest(argv=argv):
                code, _, err = self.run_cli(self.base() + ["load-set", *argv])
                self.assertEqual(code, 1)
                self.assertIn("--enrollment for wake and --task", err)

    def test_command_returns_the_load_set(self):
        state = empty_state()
        register_task(state["recovery"], {"task": "t", "base_revision": "a" * 40, "scope": "fix it",
                                          "allowed_paths": ["src/*"], "authorization": {"source": "operator", "quote": "go"}}, DEV_0)
        add_assignment(state, DEV_0, "developer", "grok", task="t")
        save_state(self.state, state)
        code, out, err = self.run_cli(self.base() + ["load-set", "--decision", "plan", "--task", "t"])
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["schema_version"], 4)
        self.assertFalse(result["history_included"])
        self.assertFalse(result["authorizes_progression"])
        self.assertEqual((result["decision"], result["core"]["task"]["scope"]), ("plan", "fix it"))
        self.assertEqual(result["records"]["reserved_developer"], ["grok"])

    def test_cli_refuses_oversized_context_without_printing_a_partial_task(self):
        state = empty_state()
        register_task(state["recovery"], {"task": "t", "base_revision": "a" * 40, "scope": "x" * OUTPUT_BYTES,
                                          "allowed_paths": ["src/*"], "authorization": {"source": "operator", "quote": "go"}}, DEV_0)
        save_state(self.state, state)
        code, out, err = self.run_cli(self.base() + ["load-set", "--decision", "plan", "--task", "t"])
        self.assertEqual((code, out), (1, ""))
        self.assertLess(len(err.encode()), 1_024)
        self.assertIn("context_budget_exceeded", err)

    def test_cli_requires_a_question_and_a_listed_evidence_reference(self):
        state = empty_state()
        register_task(state["recovery"], {"task": "t", "base_revision": "a" * 40, "scope": "fix it",
                                          "allowed_paths": ["src/*"], "authorization": {"source": "operator", "quote": "go"}}, DEV_0)
        save_state(self.state, state)
        for flags in (["--question", "Why?"], ["--read-file", "/unlisted", "--question", "Why?"]):
            with self.subTest(flags=flags):
                self.out, self.err = io.StringIO(), io.StringIO()
                code, out, err = self.run_cli(self.base() + ["load-set", "--decision", "plan", "--task", "t", *flags])
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err)

    def test_an_unknown_task_or_enrollment_fails(self):
        save_state(self.state, empty_state())
        for argv, message in ((["--decision", "plan", "--task", "ghost"], "neither registered nor assigned"),
                              (["--decision", "wake", "--enrollment", "ghost"], "no supervision enrollment")):
            with self.subTest(argv=argv):
                self.out, self.err = io.StringIO(), io.StringIO()
                code, _, err = self.run_cli(self.base() + ["load-set", *argv])
                self.assertEqual(code, 1)
                self.assertIn(message, err)

    def test_the_command_returns_context_without_writing_operational_or_read_state(self):
        state = empty_state()
        register_task(state["recovery"], {"task": "t", "base_revision": "a" * 40, "scope": "fix it",
                                          "allowed_paths": ["src/*"], "authorization": {"source": "operator", "quote": "go"}}, DEV_0)
        add_assignment(state, DEV_0, "developer", "grok", task="t")
        save_state(self.state, state)
        before = self.state.read_bytes()
        code, out, err = self.run_cli(self.base() + ["load-set", "--decision", "plan", "--task", "t"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertNotIn("aggregate_budget", json.loads(out))
        self.assertFalse(Path(str(self.state) + ".context.json").exists())

    def test_repeated_cli_reads_remain_bounded_and_preserve_all_owner_obligations(self):
        state = empty_state()
        register_task(state["recovery"], {"task": "t", "base_revision": "a" * 40, "scope": "x" * 3500,
                                          "allowed_paths": ["src/*"], "authorization": {"source": "operator", "quote": "go"}}, DEV_0)
        save_state(self.state, state)
        before = self.state.read_bytes()
        results = []
        for _ in range(20):
            self.out, self.err = io.StringIO(), io.StringIO()
            code, out, err = self.run_cli(self.base() + ["load-set", "--decision", "plan", "--task", "t"])
            self.assertEqual(code, 0, err)
            results.append(json.loads(out))
        self.assertEqual(len(results), 20)
        self.assertTrue(all("aggregate_budget" not in result for result in results))
        self.assertEqual(self.state.read_bytes(), before)
        self.assertFalse(Path(str(self.state) + ".context.json").exists())

    def test_an_unreadable_listed_path_fails_with_a_diagnostic(self):
        from foreman import cli
        with patch("foreman.cli.Path.is_file", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaisesRegex(StateError, "Cannot check /r/x.md .*restore access"):
                cli._file_present("/r/x.md")

    def test_an_unusable_state_file_fails(self):
        self.state.write_text('{"schema_version": 2, broken', encoding="utf-8")
        code, _, err = self.run_cli(self.base() + ["load-set", "--decision", "plan", "--task", "t"])
        self.assertEqual(code, 1)
        self.assertIn("unusable", err)


if __name__ == "__main__":
    unittest.main()
