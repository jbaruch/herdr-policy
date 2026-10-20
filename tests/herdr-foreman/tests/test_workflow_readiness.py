"""Readiness matches real owner preparation without claiming or dispatching work.

Native transport is private fixture transport. Git, admission, kernel leases,
process identity, frozen inputs and the production worker planner are real.
These checks do not establish live team adoption or pilot outcomes.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import io
import json
import os
from datetime import timedelta
import unittest
from unittest.mock import patch

from tests import test_workflow_service as fixture
from foreman import cli, context_output, progression_runtime, recovery, supervision
from foreman import workflow_planning, workflow_readiness as readiness
from foreman.errors import UsageError
from foreman.state import add_snapshot, save_state


class WorkflowReadinessTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.WorkflowServiceTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture

    def view(self, **options):
        return readiness.view(self.f.owner.state(), self.f.path, supervision.load(self.f.path),
                              self.f.now(), fixture.ROOT, **options)

    def one(self, **options):
        return self.view(task="one", **options)["items"][0]

    def files(self):
        return {str(path.relative_to(self.f.root)): path.read_bytes()
                for path in self.f.root.rglob("*") if path.is_file() and ".git" not in path.parts}

    def invoke(self, *arguments, client=None):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["workflow-readiness", "--state", str(self.f.path),
                         "--config", str(self.f.configuration), "--now", self.f.now(), *arguments],
                        client=client, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def snapshot(self, headroom):
        state = self.f.owner.state()
        add_snapshot(state, {"schema_version": 5, "measured_at": self.f.now(), "agents": {
            name: {"kind": name, "state": "idle", "headroom_pct": headroom}
            for name in ("claude", "codex", "grok")}, "failed_agents": [], "skipped_agents": []})
        save_state(self.f.path, state)

    def test_verified_live_owner_and_production_planner_agree_without_view_effects(self):
        self.f.admit()
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability, planner=workflow_planning.plan)
            progression_runtime.pulse(capability, self.f.now())
            before, events = self.files(), list(self.f.native.events)
            result = self.view(task="one", native_verified=True)
            row = result["items"][0]
            self.assertEqual((row["ready"], row["dispatchable"], row["reason"]),
                             (True, True, "preparation_ready"))
            self.assertFalse(result["authorizes_dispatch"])
            self.assertFalse(result["authorizes_progression"])
            self.assertEqual(self.files(), before)
            self.assertEqual(self.f.native.events, events)
            prepared = runner.tick()
            self.assertEqual(prepared["data"]["status"], "prepared")
            job = self.f.progress()["pending"]["job"]
            self.assertEqual((job["role"], job["worker_kind"]),
                             (row["responsibility"], row["worker_kind"]))
            self.assertEqual(self.f.native.events, events)

    def test_capacity_wait_matches_executor_and_has_no_planning_or_native_effect(self):
        self.f.select_backpressure()
        self.f.admit()
        self.f.foreign_enrollment()
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability, planner=workflow_planning.plan)
            before, events = self.files(), list(self.f.native.events)
            row = self.one(native_verified=True)
            self.assertEqual(self.files(), before)
            primary_before = self.f.path.read_bytes()
            actual = runner.tick()
            self.assertEqual((row["ready"], row["dispatchable"]), (True, False))
            self.assertEqual(row["reason"], actual["data"]["reason"])
            self.assertEqual(row["reason"], "global_in_flight_limit")
            self.assertEqual(row["capacity"], actual["data"]["capacity"])
            self.assertEqual(self.f.path.read_bytes(), primary_before)
            self.assertEqual(self.f.native.events, events)

    def test_existing_verification_drains_at_full_capacity(self):
        self.f.select_backpressure()
        self.f.admit()
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability)
            self.f.advance(runner, lambda: self.f.progress()["phase"] == "verify", delivery=self.f.deliver)
            self.f.foreign_enrollment()
            progression_runtime.pulse(capability, self.f.now())
            before = self.files()
            row = self.one(native_verified=True)
            self.assertEqual((row["ready"], row["dispatchable"], row["responsibility"]),
                             (True, True, "reviewer"), row)
            self.assertEqual(row["capacity"]["reason"], "drain_existing_task")
            self.assertEqual(self.files(), before)
            self.assertEqual(runner.tick()["data"]["status"], "prepared")
            self.assertEqual(self.f.progress()["pending"]["job"]["role"], "reviewer")

    def test_stale_measurement_is_unknown_and_executor_prepares_measurement(self):
        self.f.admit()
        self.f.origin += timedelta(seconds=readiness.MEASUREMENT_MAX_AGE + 1)
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability)
            before = self.files()
            row = self.one(native_verified=True)
            self.assertEqual((row["ready"], row["dispatchable"], row["reason"]),
                             (True, None, "measurement_required"))
            self.assertEqual(self.files(), before)
            self.assertEqual(runner.tick()["data"]["status"], "prepared")
            self.assertEqual(self.f.progress()["pending"]["operation"], "measure")

    def test_unadmitted_registered_task_is_unmeasured_instead_of_free_work(self):
        before = self.files()
        result = self.view()
        self.assertEqual(result["pagination"]["returned"], 2)
        self.assertEqual(result["counts"]["readiness_unmeasured"], 2)
        self.assertEqual({row["reason"] for row in result["items"]}, {"task_not_admitted"})
        self.assertEqual(result["counts"]["dispatchable"], 0)
        self.assertEqual(self.files(), before)

    def test_live_kernel_lease_and_native_foreman_are_independent_requirements(self):
        self.f.admit()
        with self.f.owner.session() as capability:
            self.f.runner(capability, planner=workflow_planning.plan)
            missing = self.one(native_verified=True)
            self.assertEqual((missing["dispatchable"], missing["reason"], missing["executor"]),
                             (None, "executor_health_unverified", "missing"))
            progression_runtime.pulse(capability, self.f.now())
            offline = self.one()
            self.assertEqual((offline["ready"], offline["dispatchable"], offline["reason"]),
                             (True, None, "native_foreman_unverified"))
        row = self.one(native_verified=True)
        self.assertIsNone(row["dispatchable"])
        self.assertEqual(row["reason"], "executor_health_unverified")
        self.assertNotEqual(row["executor"], "live")

    def test_known_exhaustion_and_unmeasured_headroom_are_not_conflated(self):
        self.f.admit()
        for headroom, expected, dispatchable in ((0.0, "quota_exhausted", False), (None, "quota_unmeasured", None)):
            with self.subTest(headroom=headroom):
                self.snapshot(headroom)
                before = self.files()
                row = self.one(native_verified=True)
                self.assertEqual((row["ready"], row["dispatchable"], row["reason"]),
                                 (True, dispatchable, expected))
                self.assertEqual(self.files(), before)

    def test_changed_contract_is_an_explicit_exclusion_without_rewriting_authority(self):
        self.f.admit()
        self.f.owner.contract.write_text(self.f.owner.contract.read_text() + "\n")
        before = self.files()
        row = self.one(native_verified=True)
        self.assertEqual((row["ready"], row["dispatchable"], row["reason"]),
                         (False, False, "contract_changed"))
        self.assertEqual(self.files(), before)

    def test_known_exhaustion_refuses_the_real_owner_before_preparation(self):
        self.f.admit()
        self.snapshot(0.0)
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability, planner=workflow_planning.plan)
            events = list(self.f.native.events)
            row = self.one(native_verified=True)
            self.assertEqual(row["reason"], "quota_exhausted")
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual(self.f.native.events, events)
            self.assertIsNone(self.f.progress()["pending"])
            self.assertEqual(self.f.owner.state()["assignments"], [])

    def test_known_exhausted_kind_does_not_hide_an_available_provider(self):
        self.f.admit()
        self.snapshot(0.0)
        state = self.f.owner.state()
        state["snapshots"][-1]["agents"]["codex"]["headroom_pct"] = 60.0
        save_state(self.f.path, state)
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability, planner=workflow_planning.plan)
            progression_runtime.pulse(capability, self.f.now())
            result = self.view(native_verified=True)
            one = next(row for row in result["items"] if row["task"] == "one")
            self.assertEqual((one["dispatchable"], one["worker_kind"]), (True, "codex"))
            self.assertEqual(result["counts_scope"], "returned_items")
            self.assertEqual(result["counts"], {"ready": 1, "not_ready": 0, "readiness_unmeasured": 1,
                "dispatchable": 1, "excluded_ready": 0, "dispatchability_unmeasured_ready": 0})
            self.assertEqual(runner.tick()["data"]["status"], "prepared")
            self.assertEqual(self.f.progress()["pending"]["job"]["worker_kind"], "codex")

    def test_quota_change_after_preparation_refuses_before_native_launch(self):
        self.f.admit()
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability)
            runner.tick()
            pending = self.f.progress()["pending"]["id"]
            self.snapshot(0.0)
            events = list(self.f.native.events)
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual(self.f.progress()["pending"]["id"], pending)
            self.assertEqual(self.f.native.events, events)
            self.assertEqual(self.f.active(), [])

    def test_shared_account_uses_its_lowest_known_headroom(self):
        self.f.admit()
        self.snapshot(0.0)
        state = self.f.owner.state()
        agents = state["snapshots"][-1]["agents"]
        agents["codex"]["headroom_pct"] = 60.0
        for kind in ("claude", "codex"):
            agents[kind]["window_group"] = "private-shared-window"
        save_state(self.f.path, state)
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability, planner=workflow_planning.plan)
            self.assertEqual(self.one(native_verified=True)["reason"], "quota_exhausted")
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual(self.f.native.events, [])

    def test_recorded_plan_stays_byte_bound_after_interrupted_preparation(self):
        self.f.admit()
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability, planner=workflow_planning.plan)
            with patch.object(runner, "_make_job", side_effect=RuntimeError("Private fixture interruption")):
                with self.assertRaisesRegex(RuntimeError, "Private fixture interruption"):
                    runner.tick()
            progression_runtime.pulse(capability, self.f.now())
            self.assertTrue(self.one(native_verified=True)["dispatchable"])
            recorded = Path(self.f.progress()["plan"]["path"])
            recorded.write_bytes(recorded.read_bytes() + b"\n")
            before = self.files()
            row = self.one(native_verified=True)
            self.assertEqual((row["dispatchable"], row["reason"]), (False, "recorded_plan_changed"))
            self.assertEqual(self.files(), before)
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual(self.f.progress()["exception"]["code"], "current_plan_changed")
            self.assertEqual(self.f.native.events, [])

    def test_changed_prerequisite_bytes_never_appear_ready(self):
        self.f.admit()
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability)
            self.f.advance(runner, lambda: self.f.progress()["phase"] == "verify", delivery=self.f.deliver)
            developer = self.f.progress()["jobs"]["developer"]
            state = self.f.owner.state()
            prior = fixture.workflow_dispatch.current_job(state, supervision.load(self.f.path), developer)
            Path(prior["report"]).write_text("Changed prerequisite bytes.\n")
            before = self.files()
            row = self.one(native_verified=True)
            self.assertEqual((row["ready"], row["dispatchable"], row["reason"]),
                             (False, False, "prerequisite_delivery_unconfirmed"))
            self.assertEqual(self.files(), before)
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertNotIn("reviewer", self.f.progress()["jobs"])

    def test_changed_source_cannot_dispatch_verification_for_an_old_head(self):
        self.f.admit()
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability)
            self.f.advance(runner, lambda: self.f.progress()["phase"] == "verify", delivery=self.f.deliver)
            self.f.source.write_text("value = 999\n")
            self.f.git("commit", "-am", "Private readiness fixture changed head")
            before = self.files()
            row = self.one(native_verified=True)
            self.assertEqual((row["ready"], row["dispatchable"], row["reason"]),
                             (False, False, "current_head_changed"))
            self.assertEqual(self.files(), before)
            self.assertEqual(runner.tick()["data"]["status"], "exception")
            self.assertEqual(len(self.f.owner.state()["assignments"]), 1)

    def test_pending_native_intent_and_enrolled_work_are_not_free_slots(self):
        self.f.admit()
        with self.f.owner.session() as capability:
            runner = self.f.runner(capability)
            runner.tick()
            before = self.files()
            pending = self.one(native_verified=True)
            self.assertEqual((pending["ready"], pending["dispatchable"], pending["reason"]),
                             (False, False, "pending_intent"))
            self.assertEqual(self.files(), before)
            self.f.advance(runner, lambda: bool(self.f.progress()["jobs"]))
            active = self.one(native_verified=True)
            self.assertEqual((active["ready"], active["dispatchable"], active["reason"]),
                             (False, False, "current_jobs_require_observation"))

    def test_offline_cli_uses_no_native_transport_and_keeps_owner_bytes(self):
        self.f.admit()
        with self.f.owner.session() as capability:
            self.f.runner(capability, planner=workflow_planning.plan)
            progression_runtime.pulse(capability, self.f.now())
            before = self.files()
            with patch.dict(os.environ, {}, clear=True), patch.object(cli, "_client", side_effect=AssertionError("offline transport")):
                code, out, err = self.invoke("--task", "one")
            self.assertEqual((code, err), (0, ""))
            result = json.loads(out)
            self.assertEqual(result["items"][0]["reason"], "native_foreman_unverified")
            self.assertEqual(result["native_foreman"], {"verified": False, "reason": "native_context_unavailable"})
            self.assertLessEqual(len(out.encode()), context_output.OUTPUT_BYTES)
            self.assertEqual(self.files(), before)

    def test_cli_verifies_actual_native_identity_instead_of_trusting_environment(self):
        self.f.admit()
        with self.f.owner.session() as capability:
            self.f.runner(capability, planner=workflow_planning.plan)
            progression_runtime.pulse(capability, self.f.now())
            code, out, err = self.invoke("--task", "one", client=self.f.owner.client)
            self.assertEqual((code, err), (0, ""))
            self.assertTrue(json.loads(out)["items"][0]["dispatchable"])
            self.f.owner.native["value"] = "different-native-session"
            code, out, err = self.invoke("--task", "one", client=self.f.owner.client)
            self.assertEqual((code, err), (0, ""))
            result = json.loads(out)
            self.assertFalse(result["native_foreman"]["verified"])
            self.assertIsNone(result["items"][0]["dispatchable"])

    def test_large_open_queue_is_bounded_and_counts_only_returned_rows(self):
        state = self.f.owner.state()
        original = state["recovery"]["tasks"]["two"]
        names = ["queue-{:03d}-{}".format(index, "\u00e9" * 300) for index in range(100)]
        for name in names:
            recovery.register_task(state["recovery"], {"task": name, **{key: original[key] for key in
                ("base_revision", "scope", "allowed_paths", "authorization")}}, self.f.now())
        save_state(self.f.path, state)
        before = self.files()
        offset, observed = 0, []
        while True:
            result = self.view(limit=50, offset=offset)
            self.assertLessEqual(len((json.dumps(result, indent=2) + "\n").encode()), context_output.OUTPUT_BYTES)
            page, counts = result["pagination"], result["counts"]
            self.assertEqual(page["total"], 102)
            self.assertEqual(page["returned"], sum(counts[key] for key in ("ready", "not_ready", "readiness_unmeasured")))
            self.assertEqual(counts["ready"], sum(counts[key] for key in
                ("dispatchable", "excluded_ready", "dispatchability_unmeasured_ready")))
            self.assertEqual(result["unexamined_in_response"], page["total"] - page["returned"])
            self.assertFalse(result["context_complete"])
            observed.extend(row["task"] for row in result["items"])
            if page["next_offset"] is None:
                break
            self.assertGreater(page["next_offset"], offset)
            offset = page["next_offset"]
        self.assertEqual(observed, sorted(["one", "two", *names]))
        self.assertEqual(self.files(), before)

    def test_closed_task_is_removed_but_active_enrollment_keeps_it_unresolved(self):
        state = self.f.owner.state()
        recovery.close_task(state["recovery"], state["assignments"],
            {"task": "two", "outcome": "merged", "evidence": "Private closure fixture."}, self.f.now())
        save_state(self.f.path, state)
        self.assertEqual([row["task"] for row in self.view()["items"]], ["one"])
        with self.assertRaises(UsageError):
            self.view(task="two")
        self.f.foreign_enrollment()
        self.assertEqual([row["task"] for row in self.view()["items"]], ["one", "two"])

    def test_unknown_oversized_and_invalid_pages_refuse_without_empty_success(self):
        before = self.files()
        for arguments in (("--task", "absent"), ("--task", "x" * 1_025),
                          ("--limit", "0"), ("--offset", "-1")):
            with self.subTest(arguments=arguments[:1]):
                with patch.dict(os.environ, {}, clear=True):
                    code, out, err = self.invoke(*arguments)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("error", json.loads(err))
                self.assertEqual(self.files(), before)

    def test_unusable_ledger_cannot_look_like_an_empty_queue(self):
        self.f.path.write_text("Unusable private owner fixture")
        before = self.files()
        with patch.object(cli, "_client", side_effect=AssertionError("unusable owner transport")):
            code, out, err = self.invoke()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("unusable ledger is not an empty queue", err)
        self.assertEqual(self.files(), before)


if __name__ == "__main__":
    unittest.main()
