"""Existing unassessed source enters independent verification under real owners.

Only the native transport and remote read are deterministic fixtures. Real Git,
source parsing, receipts, enrollment transfer, leases and workflow owners run.
No native deployment or measured live-throughput acceptance is claimed.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
import io
import json
import os
import unittest
from unittest.mock import patch

from tests import test_workflow_service as workflow_fixture
from foreman import assign, cli, delivery_collection, progression_owner as authority, recovery, supervision
from foreman import workflow_adoption as adoption, workflow_batch, workflow_contract, workflow_workspace as workspace
from foreman.errors import UsageError
from foreman.state import add_assignment, save_state, state_lock


class WorkflowAdoptionTest(unittest.TestCase):
    def setUp(self):
        self.fx = workflow_fixture.WorkflowServiceTest()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.fx.admit()
        with self.fx.owner.session() as cap:
            runner = self.fx.runner(cap)
            self.fx.advance(runner, lambda: bool(self.fx.progress()["jobs"]))
            self.source_job = self.fx.active()[0]
            self.fx.deliver(self.source_job)
        self.report = Path(self.source_job["report"])
        self.report.write_text("Legacy source delivered and pushed at " + self.fx.git("rev-parse", "HEAD").strip() + ". Independent acceptance is pending.\n")
        # Model a genuinely legacy assignment at the existing owner boundary:
        # retain canonical dispatch/assignment/enrollment history, no prior
        # executor authority, assessment, fabricated WORKFLOW or built claim.
        state = self.fx.owner.state()
        row = state["recovery"]["tasks"]["one"]
        row.pop("authority")
        row.pop("progression")
        row["schema_version"] = 1
        save_state(self.fx.path, state)
        self.fx.document["artifact_directory"] = str(self.fx.root / "adopted-current")
        self.source = self.write_source()
        native_root = patch.dict(os.environ, {"CODEX_HOME": str(self.fx.root / "codex")})
        native_root.start()
        self.addCleanup(native_root.stop)
        real_git = workspace.git
        def git(root, *arguments, **options):
            if arguments[:1] == ("ls-remote",):
                head = real_git(root, "rev-parse", "HEAD").strip()
                return head + "\trefs/heads/feature/task\n"
            return real_git(root, *arguments, **options)
        remote = patch.object(workspace, "git", side_effect=git)
        remote.start()
        self.addCleanup(remote.stop)

    def write_source(self):
        job = self.source_job
        dispatch = next(row for row in self.fx.owner.state()["recovery"]["dispatches"] if row["id"] == job["id"])
        prompt = assign.assignment_text("developer", dispatch["common"], dispatch["brief"])
        prompt, _digest = assign.tiered_prompt(prompt, dispatch["result"]["tier"], dispatch["common"], dispatch["brief"])
        session = job["native_session"]["value"]
        final = "Source is ready for independent verification.\n\nREPORT: " + str(self.report)
        rows = [
            {"type": "session_meta", "payload": {"id": session}},
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "legacy-turn"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final_answer", "content": [{"type": "output_text", "text": final}]}},
            {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "legacy-turn", "last_agent_message": final}},
        ]
        path = self.fx.root / "codex/sessions/2026/10/25" / ("rollout-legacy-" + session + ".jsonl")
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        return path

    def prepare(self):
        receipt = adoption.prepare(self.fx.path, self.fx.owner.state(), supervision.load(self.fx.path),
            self.fx.document, self.source_job["id"], client=self.fx.native)
        self.fx.document.update(schema_version=3, adoption=receipt)
        self.fx.owner.contract.write_text(json.dumps(self.fx.document))
        return receipt

    def admit(self):
        with patch.object(adoption, "LEGACY_ADOPTION_ENABLED", True), state_lock(self.fx.path):
            return authority.handoff(self.fx.path, self.fx.owner.data, self.fx.now(), self.fx.native,
                                     Path(__file__).resolve().parents[3])

    def test_reader_release_refuses_new_admission_without_owner_mutation(self):
        self.prepare()
        before = self.fx.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "reader publications"):
            with state_lock(self.fx.path):
                authority.handoff(self.fx.path, self.fx.owner.data, self.fx.now(), self.fx.owner.client,
                                  Path(__file__).resolve().parents[3])
        self.assertEqual(self.fx.path.read_bytes(), before)
        self.assertFalse(Path(self.fx.document["artifact_directory"]).exists())

    def test_reported_legacy_source_transfers_and_verifies_without_a_built_claim(self):
        receipt = self.prepare()
        before = copy.deepcopy(self.fx.owner.state())
        self.admit()
        self.assertEqual(self.fx.progress()["phase"], "verify")
        self.assertEqual(self.fx.progress()["pending"]["operation"], "adopt")
        with self.fx.owner.session() as cap:
            runner = self.fx.runner(cap)
            self.assertEqual(runner.tick()["data"]["status"], "effect_recorded")
            member = supervision.load(self.fx.path)["members"][0]
            self.assertFalse(member["active"])
            self.assertEqual(member["resolution"]["outcome"], adoption.transfer_outcome(self.fx.document))
            self.assertEqual(runner.tick()["data"]["status"], "advanced")
            self.fx.advance(runner, lambda: bool(self.fx.progress()["jobs"].get("reviewer")))
            reviewer = self.fx.active()[0]
            self.assertNotEqual(reviewer["agent"], self.source_job["agent"])
            self.assertIn(str(self.report), Path(reviewer["brief"]).read_text())
            self.assertIn("source_adoption", Path(reviewer["brief"]).read_text())
            self.fx.deliver(reviewer)
            self.fx.advance(runner, lambda: self.fx.progress()["phase"] == "release")
        state = self.fx.owner.state()
        self.assertEqual(state["assignments"][0], before["assignments"][0])
        self.assertEqual(state["recovery"]["tasks"]["one"]["base_revision"], self.fx.base)
        self.assertEqual(receipt["source_status"], "reported")
        self.assertNotIn("WORKFLOW:", self.report.read_text())
        self.assertEqual([row["role"] for row in state["assignments"]], ["developer", "reviewer"])

    def test_changed_head_and_missing_native_provenance_are_task_local_refusals(self):
        self.prepare()
        self.fx.source.write_text("value = 100\n")
        self.fx.git("commit", "-am", "Private changed source head")
        before = self.fx.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "current source head|changed after preparation"):
            self.admit()
        self.assertEqual(self.fx.path.read_bytes(), before)
        self.source.unlink()
        with self.assertRaisesRegex(UsageError, "native final-source"):
            self.prepare()
        self.assertEqual(self.fx.path.read_bytes(), before)

    def test_duplicate_collection_adds_one_observation_and_never_accepts(self):
        def check(path, identifier, **options):
            with state_lock(path):
                pass
            return {"wait": json.dumps({"agent": self.source_job["agent"],
                "report_path": str(self.report), "found": True, "reason": "completed"})}, 0
        actual_collect = delivery_collection.collect
        def collect(*args, **kwargs):
            return actual_collect(*args, **kwargs, check=check)
        for _ in range(2):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(delivery_collection, "collect", side_effect=collect):
                code = cli.main(["collect-deliveries", "--state", str(self.fx.path), "--now", self.fx.now()],
                                client=self.fx.native, stdout=out, stderr=err)
            self.assertEqual(code, 0, err.getvalue())
            result = json.loads(out.getvalue())
            self.assertEqual(result["items"][0]["status"], "collected")
            self.assertFalse(result["authorizes_acceptance"])
        observed = supervision.load(self.fx.path)
        self.assertEqual(len([row for row in observed["events"] if row["kind"] == "report_observed"]), 1)
        self.assertTrue(observed["members"][0]["active"])
        self.assertIsNone(observed["members"][0]["resolution"])

    def test_interrupted_adopted_launch_reads_back_without_a_duplicate_native_send(self):
        self.prepare()
        self.admit()
        with self.fx.owner.session() as cap:
            runner = self.fx.runner(cap)
            runner.tick()  # Original source transfer.
            runner.tick()  # Canonical transfer readback.
            self.assertEqual(runner.tick()["data"]["status"], "prepared")
            self.assertEqual(runner.tick()["data"]["status"], "effect_recorded")
            self.assertIsNotNone(self.fx.progress()["pending"])
        prompts = len([event for event in self.fx.native.events if event[0] == "prompt"])
        with self.fx.owner.session() as cap:
            result = self.fx.runner(cap).tick()
            self.assertEqual(result["data"]["status"], "advanced")
            self.assertIsNone(self.fx.progress()["pending"])
        self.assertEqual(len([event for event in self.fx.native.events if event[0] == "prompt"]), prompts)
        self.assertEqual(prompts, 2)

    def test_cumulative_original_corrections_and_contributors_survive_adoption(self):
        state = self.fx.owner.state()
        original = copy.deepcopy(state["assignments"][0])
        prior = []
        for count in (None, 1, 2):
            row = copy.deepcopy(original)
            row.update(agent="original-contributor-{}".format(count or 0), fix_round=count,
                       at="2026-10-18T00:00:0{}+00:00".format(count or 0))
            prior.append(row)
        original["fix_round"] = 3
        state["assignments"] = [*prior, original]
        source = state["recovery"]["dispatches"][0]
        source.update(fix_round=3, assignment_index=3)
        source["result"]["fix_round"] = 3
        save_state(self.fx.path, state)
        receipt = self.prepare()
        self.admit()
        self.assertEqual(receipt["correction"], 3)
        self.assertEqual(self.fx.progress()["round"], 3)
        self.assertEqual(recovery.task_statuses(self.fx.owner.state()["recovery"],
            self.fx.owner.state()["assignments"])["one"]["remaining_fixes"], 2)
        self.assertEqual(self.fx.owner.state()["assignments"], state["assignments"])
        self.assertEqual(self.fx.owner.state()["recovery"]["tasks"]["one"]["base_revision"], self.fx.base)

    def test_attributable_task_fault_holds_adoption_and_collection_without_repair(self):
        state = self.fx.owner.state()
        state["assignments"][0].update(cleared=False, clear_reason="automatic")
        self.fx.path.write_text(json.dumps(state))
        original = self.fx.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "contradictory assignment evidence"):
            self.prepare()
        def check(*args, **kwargs):
            return {"wait": json.dumps({"agent": self.source_job["agent"],
                "report_path": str(self.report), "found": True, "reason": "completed"})}, 0
        result = delivery_collection.collect(self.fx.path, self.fx.native, self.fx.now(), check=check)
        self.assertEqual(result["items"][0]["status"], "decision")
        self.assertEqual(result["items"][0]["reason"], "task_evidence_held")
        self.assertEqual(self.fx.path.read_bytes(), original)
        self.assertTrue(supervision.load(self.fx.path)["members"][0]["active"])

    def test_native_startup_preserves_another_tasks_concurrent_assignment(self):
        self.prepare()
        self.admit()
        native_create = self.fx.native.workspace_create
        def create(**options):
            # This owner transaction occurs during native startup. It must
            # succeed and retain its row through all later send callbacks.
            with state_lock(self.fx.path):
                state = self.fx.owner.state()
                add_assignment(state, self.fx.now(), "developer", "other-task-contributor", task="two",
                               cleared=True, clear_reason="automatic")
                save_state(self.fx.path, state)
            return native_create(**options)
        with self.fx.owner.session() as cap:
            runner = self.fx.runner(cap)
            actual_plan = runner.planner
            def plan(*args, **kwargs):
                with state_lock(self.fx.path):
                    pass
                return actual_plan(*args, **kwargs)
            runner.planner = plan
            with patch.object(self.fx.native, "workspace_create", side_effect=create):
                self.fx.advance(runner, lambda: bool(self.fx.progress()["jobs"].get("reviewer")))
        state = self.fx.owner.state()
        self.assertEqual([row["task"] for row in state["assignments"]], ["one", "two", "one"])
        reviewer = next(row for row in state["recovery"]["dispatches"] if row["role"] == "reviewer")
        self.assertEqual(reviewer["assignment_index"], 2)
        self.assertEqual(state["assignments"][1]["agent"], "other-task-contributor")

    def test_three_task_batch_starts_legacy_verification_despite_decision_and_invalid_input(self):
        self.prepare()
        self.admit()
        state = self.fx.owner.state()
        template_grant = state["recovery"]["tasks"]["one"]["authority"]
        for name in ("two", "three"):
            if name == "three":
                recovery.register_task(state["recovery"], {"task": name, "base_revision": self.fx.base,
                    "scope": "Private independent fixture", "allowed_paths": ["src/*"],
                    "authorization": self.fx.owner.data["authorization"]}, self.fx.now())
            document = copy.deepcopy(self.fx.document)
            document.pop("adoption")
            document.update(schema_version=2, task=name, artifact_directory=str(self.fx.root / name))
            path = self.fx.root / (name + ".json")
            path.write_text(json.dumps(document))
            grant = copy.deepcopy(template_grant)
            grant.update(schema_version=2, contract_schema=2, contract=workspace.capture(path)[0],
                         lease_path=str(self.fx.root / (name + ".lease")), service_id="service-" + name)
            progress = workflow_contract.initial_progress(1, self.fx.now())
            if name == "two":
                progress.update(phase="exception", exception={"id": "d" * 64,
                    "code": "verification_decision_required", "phase": "verify", "sources": [str(self.report)],
                    "actions": ["resolve_task_decision"]})
            else:
                document["common"]["sha256"] = "f" * 64
                path.write_text(json.dumps(document))
                grant["contract"] = workspace.capture(path)[0]
            state["recovery"]["tasks"][name].update(schema_version=2, authority=grant, progression=progress)
        save_state(self.fx.path, state)
        before = len([event for event in self.fx.native.events if event[0] == "prompt"])
        actual_cycle = workflow_batch.cycle
        def cycle(*args, **kwargs):
            return actual_cycle(*args, **kwargs, root=Path(__file__).resolve().parents[3],
                                factory=lambda cap, client: self.fx.runner(cap))
        out, err = io.StringIO(), io.StringIO()
        with patch.object(workflow_batch, "cycle", side_effect=cycle), patch.object(cli, "now_iso", side_effect=self.fx.now):
            code = cli.main(["progression-batch", "--state", str(self.fx.path), "--once"],
                            client=self.fx.native, stdout=out, stderr=err)
        self.assertEqual(code, 0, err.getvalue())
        result = json.loads(out.getvalue())
        items = {row["task"]: row for row in result["items"]}
        self.assertEqual(items["two"]["status"], "exception", result)
        self.assertEqual(items["three"]["status"], "decision")
        self.assertIn("reviewer", items["one"]["jobs"])
        self.assertEqual(len([event for event in self.fx.native.events if event[0] == "prompt"]), before + 1)
        self.assertTrue(result["context_complete"])
        self.assertEqual(self.fx.progress()["round"], 0)


if __name__ == "__main__":
    unittest.main()
