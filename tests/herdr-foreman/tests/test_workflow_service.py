"""Native lifecycle and canonical owners in isolated Git/Herdr fixtures.

These fixtures prove source behavior, never a live Herdr handoff or pilot.
Only native transport, report-check subprocesses and worker choice are faked;
the task capability, kernel lease, Git, journals, assessments and gates run.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.test_cli import FreshOwnerNative
from tests import test_progression_owner as owner_fixture
from tests.test_workflow_contract import contract as declaration, ready_snapshot
from foreman import config, policy_paths, progression_owner as authority, recovery, report_delivery, report_gates, supervision, tiers
from foreman import workflow_dispatch, workflow_planning, workflow_review, workflow_service
from foreman.errors import ForemanError, HerdrError
from foreman.herdr import HerdrClient
from foreman.workflow_workspace import inspect as inspect_workspace
from foreman.errors import UsageError
from foreman.state import add_snapshot, save_state, state_lock
from foreman.workflow_native import NativeWorkflowAdapter

ROOT = owner_fixture.ROOT


class WorkflowNativeFixture(FreshOwnerNative):
    """A fixture transport, instrumented at every fake mutating boundary."""
    def __init__(self, foreman=None):
        super().__init__()
        self.foreman = foreman
        self.capability = None
        self.reject_prompt = False

    def effect(self):
        assert self.capability is not None
        assert self.capability._prepared is not None
        self.capability.lease.require_current()
        self.capability._prepared["before_effect"]()

    def pane_get(self, pane_id):
        if pane_id == "fixture-pane" and self.foreman is not None:
            return self.foreman.pane_get(pane_id)
        return super().pane_get(pane_id)

    def workspace_create(self, **options):
        self.effect()
        self.sent_text = None
        self.frames = [self.EMPTY]
        return super().workspace_create(**options)

    def agent_start(self, *args, **options):
        self.effect()
        return super().agent_start(*args, **options)

    def agent_prompt(self, *args, **options):
        self.effect()
        if self.reject_prompt:
            raise HerdrError("Fixture transport result is unknown.", {})
        return super().agent_prompt(*args, **options)

    def pane_close(self, pane_id):
        self.effect()
        return super().pane_close(pane_id)

    def pane_rename(self, pane_id, label):
        self.effect()
        return super().pane_rename(pane_id, label)


class WorkflowServiceTest(unittest.TestCase):
    def setUp(self):
        self.owner = owner_fixture.ProgressionOwnerTest()
        self.owner.setUp()
        self.addCleanup(self.owner.doCleanups)
        self.root, self.path = self.owner.root, self.owner.path
        self.worktree = self.root / "writer"
        self.repository = self.root / "repository"
        self.repository.mkdir()
        # Build a real additional worktree, so task-local teardown can never
        # be inferred to authorize deleting the repository's main checkout.
        self.worktree = self.repository
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Private fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.worktree / "src").mkdir()
        self.source = self.worktree / "src/example.py"
        self.source.write_text("value = 0\n")
        self.git("add", "src/example.py")
        self.git("commit", "-m", "Private fixture base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("remote", "add", "origin", "https://github.com/fixture/repository.git")
        self.git("worktree", "add", "-b", "feature/task", str(self.root / "writer"))
        self.worktree = self.root / "writer"
        self.source = self.worktree / "src/example.py"
        # A private complete policy-lookup fixture, not a live installation.
        # The release subprocess ABI and actual published installations have
        # separate coverage; these files are never executed as helper code.
        policy_root = self.repository / ".tessl/plugins/jbaruch/coding-policy/skills/release"
        for relative in policy_paths.RELEASE_FILES:
            path = policy_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Private compatible policy lookup fixture.\n")
        (self.repository / ".tessl/RULES.md").write_text("Private general policy fixture.\n")
        with (self.repository / ".git/info/exclude").open("a") as stream:
            stream.write("\n.tessl/\n")
        self.configuration = self.root / "config.json"
        self.configuration.write_bytes((ROOT / "skills/herdr-foreman/config.example.json").read_bytes())
        self.common = self.root / "common-template.md"
        self.common.write_text("Private fixture report contract.\n")
        self.document = declaration()
        self.document.update(task="one", config=recovery.receipt(str(self.configuration))[0],
            common=recovery.receipt(str(self.common))[0], artifact_directory=str(self.root / "current"))
        self.document["repository"]["worktree"] = str(self.worktree)
        self.templates = {}
        for role in ("developer", "reviewer", "tester", "release"):
            source = self.root / (role + "-template.md")
            source.write_text("Private fixture {} instructions.\n".format(role))
            self.templates[role] = recovery.receipt(str(source))[0]
        self.document["briefs"] = {role: self.templates[role] for role in ("developer", "reviewer", "release")}
        self.origin = datetime(2026, 10, 19, tzinfo=timezone.utc)
        self.ordinal, self.clock_calls = 0, 0
        state = self.owner.state()
        state["recovery"]["tasks"]["one"]["base_revision"] = self.base
        add_snapshot(state, {"schema_version": 5, "measured_at": self.now(), "agents": {
            name: {"kind": name, "state": "idle", "headroom_pct": 90.0}
            for name in ("claude", "codex", "grok")}, "failed_agents": [], "skipped_agents": []})
        save_state(self.path, state)
        self.native = WorkflowNativeFixture(self.owner.client)
        self.change = 0
        self.wait_fault = None

    def now(self):
        self.clock_calls += 1
        return (self.origin + timedelta(seconds=self.clock_calls)).isoformat()

    def git(self, *arguments):
        return subprocess.run(["git", "-C", str(self.worktree), *arguments], check=True,
                              capture_output=True, text=True).stdout

    def admit(self, *, complex_work=False):
        if complex_work:
            self.document["risk"]["cross_repository"] = True
            self.document["briefs"]["tester"] = self.templates["tester"]
        self.owner.contract.write_text(json.dumps(self.document))
        with state_lock(self.path):
            authority.handoff(self.path, self.owner.data, self.now(), self.owner.client, ROOT)

    def plan(self, state, path, document, progress, roles, agents, at):
        self.ordinal += 1
        worker = next(agent for agent in agents if agent.name == "codex")
        return {"schema_version": 18, "assignments": {role: "{}-fixture-{}".format(role, self.ordinal) for role in roles},
            "worker_kinds": {role: "codex" for role in roles},
            "tiers": {role: tiers.select_tier(worker, role, fix_round=progress["round"] or None) for role in roles}}

    def wait(self, argv, **options):
        # The real --once owner is used; only its subprocess transport is fake.
        with state_lock(self.path):
            pass
        agent, report = argv[-2:]
        found = Path(report).is_file()
        waited = {"agent": agent, "report_path": report, "found": found,
                  "reason": "completed" if found else "checkpoint_pending", "elapsed_seconds": 1}
        code = 0 if found else 1
        if self.wait_fault is not None:
            waited.update(reason=self.wait_fault, stall={"fixture": True})
            code = 1
        return subprocess.CompletedProcess(argv, code, json.dumps(waited), "")

    def adapter(self, *args, **options):
        return NativeWorkflowAdapter(*args, **options, run=self.wait)

    def runner(self, capability):
        self.native.capability = capability
        # FreshOwnerNative overrides methods instead of emulating JSON argv.
        # Actual clone/fence behavior is independently tested by owner suites.
        patched = patch.object(capability, "authorized_client", return_value=self.native)
        patched.start()
        self.addCleanup(patched.stop)
        return workflow_service.WorkflowService(capability, self.native, clock=self.now, sleeper=lambda _: None,
                                                native=self.adapter, planner=self.plan)

    def progress(self):
        return self.owner.state()["recovery"]["tasks"]["one"]["progression"]

    def active(self):
        state, supervised = self.owner.state(), supervision.load(self.path)
        return [workflow_dispatch.current_job(state, supervised, row["id"]) for row in supervised["members"] if row["active"]]

    def deliver(self, job, *, outcome=None, advisory=False, cause_settled=True, implement=True):
        role = job["role"]
        if role == "developer" and implement:
            self.change += 1
            self.source.write_text("value = {}\n".format(self.change))
            self.git("add", "src/example.py")
            self.git("commit", "-m", "Private fixture implementation {}".format(self.change))
        head = self.git("rev-parse", "HEAD").strip()
        reviewing = role in ("reviewer", "tester")
        selected = outcome or ("built" if role == "developer" else "delivered" if role == "release" else "verified")
        correction = {field: field in {"scope_unchanged", "cause_settled"} for field in workflow_service.schema.REVIEW_CONTEXT}
        correction["cause_settled"] = cause_settled
        findings = ([{"schema_version": 1, "id": "fixture-defect", "severity": "blocking", "status": "open"}]
                    if selected == "blocking" else [{"schema_version": 1, "id": "fixture-advice", "severity": "advisory", "status": "open"}] if advisory else [])
        claim = {"schema_version": 1, "task": "one", "head_revision": head,
            "responsibilities": workflow_service.schema.responsibilities(workflow_service.schema.contract(
                self.document, self.owner.state()["recovery"]["tasks"]["one"]), role), "outcome": selected,
            "acceptance": [{"criterion": 1, "state": "met" if selected == "verified" else "unmet", "evidence": "Private independent fixture check."}] if reviewing else None,
            "checks": [{"responsibility": responsibility, "name": "fixture " + responsibility,
                        "result": "passed", "evidence": "Private fixture assertions."}
                       for responsibility in workflow_service.schema.responsibilities(workflow_service.schema.contract(
                           self.document, self.case_task()), role)],
            "findings": findings, "correction": correction if reviewing else None,
            "pull_request": 123 if role == "release" else None,
            "review_snapshot": "c" * 64 if role == "release" else None,
            "review_evidence": None, "publication": None}
        if role == "release" and selected == "delivered":
            snapshot = ready_snapshot(head)
            review_path = Path(self.document["artifact_directory"]) / "reviews-{}.json".format(job["id"].replace(":", "-"))
            review_path.write_text(json.dumps(snapshot))
            claim.update(review_snapshot=workflow_review.identity(snapshot)["sha256"],
                review_evidence=recovery.receipt(str(review_path))[0], publication={"schema_version": 1,
                    "baseline": None, "baseline_at": None, "publisher_run": None, "tag": None, "tessl_version": None})
        verdict = "VERDICT: {}\n".format("approved" if selected == "verified" else "blocking") if reviewing else ""
        Path(job["report"]).write_text(verdict + "WORKFLOW: " + json.dumps(claim) + "\n")
        return claim

    def test_remote_owner_cannot_admit_a_schema_two_task(self):
        self.owner.contract.write_text(json.dumps(self.document))
        remote = SimpleNamespace(context=SimpleNamespace(mode="attested-remote"))
        before = self.path.read_bytes()
        with state_lock(self.path), patch("foreman.progression_owner.verify_foreman", return_value=supervision.load(self.path)), self.assertRaisesRegex(UsageError, "verified native foreman"):
            authority.handoff(self.path, self.owner.data, self.now(), remote, ROOT)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(Path(self.document["artifact_directory"]).exists())

    def test_foreign_pane_and_wrong_cwd_cannot_start_the_executor(self):
        self.admit()
        before = self.path.read_bytes()
        with self.owner.session() as capability:
            with patch.dict(os.environ, {"HERDR_PANE_ID": "foreign-managed-pane"}), self.assertRaises(ForemanError):
                self.runner(capability)
            with patch("foreman.progression_owner.Path.cwd", return_value=self.root), self.assertRaises(ForemanError):
                self.runner(capability)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.owner.state()["assignments"], [])

    def test_changed_foreman_identity_cannot_advance_or_mutate_the_task(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            runner.tick()
            before = self.path.read_bytes()
            self.owner.native["value"] = "replacement-foreman-session"
            with self.assertRaises(ForemanError):
                runner.tick()
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(self.owner.state()["assignments"], [])

    def test_actual_transport_guard_rechecks_the_live_native_foreman(self):
        self.admit()
        effects = []
        def forbidden(argv):
            effects.append(argv)
            raise AssertionError("An unverified actor reached native effects")
        client = HerdrClient(runner=forbidden)
        client.pane_get = self.owner.client.pane_get
        with self.owner.session() as capability:
            self.runner(capability).tick()
            # Use the actual transport fence, without the fixture's normal
            # authorized_client override for method-based native emulation.
            with state_lock(self.path), capability.workflow_operation(self.owner.state(), "apply", before_effect=lambda: effects.append("intent")):
                guarded = authority.ServiceCapability.authorized_client(capability, client)
                self.owner.native["value"] = "replacement-foreman-session"
                with self.assertRaises(ForemanError):
                    guarded.pane_close("unused-fixture-target")
        self.assertEqual(effects, [])

    def test_missing_startup_identity_still_runs_the_canonical_stall_checkpoint(self):
        original = self.native.agent_start
        def unidentified(name, *args, **options):
            result = original(name, *args, **options)
            self.native.agents[name]["agent_session"] = None
            result["agent"]["agent_session"] = None
            return result
        self.admit()
        with self.owner.session() as capability, patch.object(self.native, "agent_start", side_effect=unidentified):
            runner = self.runner(capability)
            self.advance(runner, lambda: bool(self.progress()["jobs"]))
            self.assertIsNone(self.active()[0]["native_session"])
            self.wait_fault = "idle_without_report"
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertEqual(result["data"]["reason"], "native_delivery_exception")

    def test_foreground_contention_waits_without_mutating_or_repeating_a_dispatch(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            runner.tick()
            before = self.path.read_bytes()
            with state_lock(self.path):
                result = runner.tick()
            self.assertFalse(result["wake_agent"])
            self.assertEqual(result["data"]["reason"], "owner_transaction_busy")
            self.assertEqual(self.path.read_bytes(), before)
            runner.tick()
            runner.tick()
        self.assertEqual(len(self.owner.state()["assignments"]), 1)

    def test_admission_preserves_existing_artifact_directory_contents(self):
        root = Path(self.document["artifact_directory"])
        root.mkdir(mode=0o700)
        prior = root / "plan.json"
        prior.write_text('existing owner content\n')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(UsageError, "fresh private artifact directory"):
            self.admit()
        self.assertEqual(prior.read_text(), 'existing owner content\n')
        self.assertEqual(self.path.read_bytes(), before)

    def test_close_preserves_a_replacement_native_session(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: bool(self.progress()["jobs"]))
            job = self.active()[0]
            self.deliver(job)
            runner.tick()
            self.native.agents[job["agent"]]["agent_session"]["value"] = "replacement-native-session"
            result = runner.tick()
        self.assertTrue(result["wake_agent"])
        self.assertIn(job["pane_id"], self.native.panes)
        self.assertTrue(next(row for row in supervision.load(self.path)["members"] if row["id"] == job["id"])["active"])

    def test_close_replays_an_actually_absent_agent_and_pane(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: bool(self.progress()["jobs"]))
            job = self.active()[0]
            self.deliver(job)
            runner.tick()
            self.native.agents.pop(job["agent"])
            self.native.panes.pop(job["pane_id"])
            self.assertEqual(runner.tick()["data"]["status"], "effect_recorded")
            self.assertEqual(runner.tick()["data"]["status"], "advanced")
        self.assertFalse(next(row for row in supervision.load(self.path)["members"] if row["id"] == job["id"])["active"])

    def test_rename_cannot_delete_an_unauthorized_source_path(self):
        private = self.worktree / "private/config.py"
        private.parent.mkdir()
        private.write_text("private_fixture = True\n")
        self.git("add", "private/config.py")
        self.git("commit", "-m", "Private fixture scope base")
        task = {**self.case_task(), "base_revision": self.git("rev-parse", "HEAD").strip()}
        self.git("mv", "private/config.py", "src/config.py")
        self.git("commit", "-m", "Private fixture out-of-scope rename")
        with self.assertRaisesRegex(UsageError, "allowed paths"):
            inspect_workspace(self.document, task, built=True)

    def case_task(self):
        return self.owner.state()["recovery"]["tasks"]["one"]

    def advance(self, runner, predicate, *, delivery=None, limit=75):
        results = []
        for _ in range(limit):
            if predicate():
                return results
            if delivery:
                for job in self.active():
                    if not Path(job["report"]).exists():
                        delivery(job)
            result = runner.tick()
            results.append(result)
            self.assertNotEqual(result["data"]["status"], "exception", result)
        self.fail("Workflow did not reach its expected fixture phase: {}".format(self.progress()))

    def test_normal_native_flow_reaches_release_without_a_foreman_relay(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: self.progress()["phase"] == "merge", delivery=self.deliver)
            state = self.owner.state()
            self.assertEqual([row["role"] for row in state["assignments"]], ["developer", "reviewer", "release"])
            self.assertEqual(len({row["agent"] for row in state["assignments"]}), 3)
            self.assertEqual(len(state["specialist_assessments"]), 1)
            self.assertEqual(len([event for event in self.native.events if event[0] == "prompt"]), 3)
            self.assertEqual(self.active(), [])
            self.assertEqual(report_gates.open_verdict_gates(self.path, "one", state["recovery"]["dispatches"]), [])
            self.assertEqual(supervision.pending(supervision.load(self.path)), [])

    def assert_changed_dependency_refuses_transport(self, runner, report):
        expected = recovery.receipt(report)[0]
        self.assertIn(expected, self.progress()["pending"]["inputs"])
        original = Path(report).read_bytes()
        Path(report).write_bytes(original + b"Private concurrent report edit.\n")
        before = list(self.native.events)
        result = runner.tick()
        self.assertEqual(result["data"]["status"], "exception", result)
        self.assertFalse(self.progress()["pending"]["effects_started"])
        self.assertEqual(self.native.events, before)
        self.assertEqual(Path(report).read_bytes(), original + b"Private concurrent report edit.\n")

    def test_prerequisite_report_is_rechecked_before_dependent_transport(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: self.progress()["phase"] == "verify", delivery=self.deliver)
            developer = workflow_dispatch.current_job(self.owner.state(), supervision.load(self.path), self.progress()["jobs"]["developer"])
            self.advance(runner, lambda: self.progress()["pending"] is not None
                and self.progress()["pending"]["operation"] == "apply")
            self.assert_changed_dependency_refuses_transport(runner, developer["report"])

    def test_blocking_report_is_rechecked_before_correction_transport(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: self.progress()["phase"] == "implement" and self.progress()["round"] == 1,
                delivery=lambda job: self.deliver(job, outcome="blocking" if job["role"] == "reviewer" else None))
            report = self.progress()["blockers"][0]["path"]
            self.advance(runner, lambda: self.progress()["pending"] is not None
                and self.progress()["pending"]["operation"] == "apply")
            self.assert_changed_dependency_refuses_transport(runner, report)

    def test_ready_release_continues_without_claiming_delivery_or_resetting_the_task(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: self.progress()["phase"] == "release", delivery=self.deliver)
            self.advance(runner, lambda: bool(self.progress()["jobs"].get("release")))
            prior = self.active()[0]
            self.deliver(prior, outcome="ready")
            self.advance(runner, lambda: self.progress()["pending"] is None and not self.active())
            self.assertEqual(runner.tick()["data"]["status"], "advanced")
            self.assertEqual(self.progress()["phase"], "release")
            self.assertIsNone(self.progress()["delivery"])
            self.assertEqual(self.progress()["round"], 0)
            self.assertNotIn("release", self.progress()["jobs"])
            self.advance(runner, lambda: bool(self.progress()["jobs"].get("release")))
            current = self.active()[0]
            self.assertNotEqual(current["id"], prior["id"])
            self.assertNotEqual(current["agent"], prior["agent"])
            self.assertNotEqual(current["report"], prior["report"])
            self.assertNotEqual(current["brief"], prior["brief"])
            self.assertTrue(Path(prior["report"]).is_file())
            self.deliver(current)
            self.advance(runner, lambda: self.progress()["phase"] == "merge")
            self.assertFalse(self.progress()["delivery"]["accepted"])
            self.assertEqual([row["role"] for row in self.owner.state()["assignments"]],
                             ["developer", "reviewer", "release", "release"])

    def test_blocked_developer_at_clean_base_closes_and_wakes_without_an_implementation_head(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: bool(self.progress()["jobs"]))
            self.deliver(self.active()[0], outcome="blocked", implement=False)
            self.advance(runner, lambda: self.progress()["pending"] is None and not self.active())
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertEqual(self.progress()["exception"]["code"], "worker_blocked")
            self.assertIsNone(self.progress()["head"])
            self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.base)
            self.assertEqual(len(self.owner.state()["assignments"]), 1)

    def test_empty_built_claim_cannot_become_an_implementation_head(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: bool(self.progress()["jobs"]))
            self.deliver(self.active()[0], implement=False)
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertEqual(self.progress()["exception"]["code"], "report_contract_refused")
            self.assertIsNone(self.progress()["head"])
            self.assertEqual(len(self.active()), 1)

    def test_post_close_report_edit_cannot_manufacture_correction_input(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: self.progress()["phase"] == "verify", delivery=self.deliver)
            self.advance(runner, lambda: bool(self.progress()["jobs"].get("reviewer")))
            job = self.active()[0]
            self.deliver(job)
            self.advance(runner, lambda: self.progress()["pending"] is None and not self.active())
            self.deliver(job, outcome="blocking")
            changed = Path(job["report"]).read_bytes()
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertEqual(self.progress()["exception"]["code"], "evidence_owner_refused")
            self.assertEqual(self.progress()["round"], 0)
            self.assertEqual(self.progress()["blockers"], [])
            self.assertEqual(len(self.owner.state()["assignments"]), 2)
            self.assertEqual(Path(job["report"]).read_bytes(), changed)

    def test_waiting_writes_no_primary_history_and_checks_outside_its_lock(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: bool(self.progress()["jobs"]))
            before = self.path.read_bytes()
            for _ in range(3):
                self.assertEqual(runner.tick()["data"]["status"], "waiting")
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(len(self.native.agents), 1)

    def test_applied_readback_after_restart_never_sends_twice(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.assertEqual(runner.tick()["data"]["status"], "prepared")
            self.assertEqual(runner.tick()["data"]["status"], "effect_recorded")
            runner = self.runner(capability)
            self.assertEqual(runner.tick()["data"]["status"], "advanced")
            self.assertEqual(len([event for event in self.native.events if event[0] == "prompt"]), 1)
            self.assertIsNone(self.progress()["pending"])

    def test_uncertain_effect_preserves_original_intent_and_never_respawns(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            runner.tick()
            identifier = self.progress()["pending"]["id"]
            self.native.reject_prompt = True
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertTrue(self.progress()["pending"]["effects_started"])
            self.assertEqual(self.progress()["pending"]["id"], identifier)
            before = list(self.native.events)
            self.assertEqual(self.runner(capability).tick()["data"]["status"], "exception")
            self.assertEqual(self.native.events, before)

    def test_complex_work_has_separate_native_review_and_test_jobs(self):
        self.admit(complex_work=True)
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: self.progress()["phase"] == "merge", delivery=self.deliver)
            state = self.owner.state()
            self.assertEqual([row["role"] for row in state["assignments"]], ["developer", "reviewer", "tester", "release"])
            self.assertEqual(len({row["agent"] for row in state["assignments"]}), 4)
            self.assertEqual(len(state["specialist_assessments"]), 2)

    def test_terminal_code_one_stall_is_an_exception(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: bool(self.progress()["jobs"]))
            self.wait_fault = "no_report_stall"
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertEqual(self.progress()["exception"]["code"], "native_delivery_exception")
            self.assertEqual(len(self.active()), 1)

    def test_settled_blocking_finding_corrects_same_task_and_independent_recheck_clears_gate(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            def deliver(job):
                blocking = job["role"] == "reviewer" and self.progress()["round"] == 0
                self.deliver(job, outcome="blocking" if blocking else None)
            self.advance(runner, lambda: self.progress()["phase"] == "merge", delivery=deliver)
            state = self.owner.state()
            self.assertEqual(self.progress()["round"], 1)
            self.assertEqual([row["role"] for row in state["assignments"]],
                             ["developer", "reviewer", "developer", "reviewer", "release"])
            self.assertEqual({row["task"] for row in state["assignments"]}, {"one"})
            developers = [row for row in state["recovery"]["dispatches"] if row["role"] == "developer"]
            self.assertEqual([row["fix_round"] for row in developers], [None, 1])
            gates = report_gates.load(self.path)["gates"]
            self.assertEqual(len(gates), 1)
            self.assertEqual(gates[0]["status"], "cleared")
            self.assertEqual(gates[0]["resolution"]["by"], "worker")
            self.assertNotEqual(gates[0]["report"], gates[0]["resolution"]["evidence"]["path"])

    def test_advisory_does_not_add_implementation_or_verification_round(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: self.progress()["phase"] == "merge",
                         delivery=lambda job: self.deliver(job, advisory=job["role"] == "reviewer"))
            self.assertEqual(self.progress()["round"], 0)
            self.assertEqual(len(self.owner.state()["assignments"]), 3)

    def test_causal_uncertainty_is_task_local_and_does_not_start_another_writer(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            unaffected = self.owner.state()["recovery"]["tasks"]["two"]
            self.advance(runner, lambda: self.progress()["phase"] == "verify", delivery=self.deliver)
            self.advance(runner, lambda: bool(self.progress()["jobs"].get("reviewer")))
            self.deliver(self.active()[0], cause_settled=False)
            result = None
            for _ in range(5):
                result = runner.tick()
                if result["data"]["status"] == "exception":
                    break
            assert result is not None
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertEqual(self.progress()["exception"]["code"], "verification_decision_required")
            self.assertEqual(self.progress()["round"], 0)
            self.assertEqual(len(self.owner.state()["assignments"]), 2)
            self.assertEqual(self.owner.state()["recovery"]["tasks"]["two"], unaffected)
            self.assertEqual(supervision.load(self.path)["holds"], [])

    def test_current_git_change_cannot_reuse_a_verifiers_old_head_claim(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            self.advance(runner, lambda: self.progress()["phase"] == "verify", delivery=self.deliver)
            self.advance(runner, lambda: bool(self.progress()["jobs"].get("reviewer")))
            self.deliver(self.active()[0])
            self.source.write_text("value = 999\n")
            self.git("commit", "-am", "Private fixture head changed during verification")
            result = runner.tick()
            self.assertEqual(result["data"]["status"], "exception", result)
            self.assertEqual(self.progress()["exception"]["code"], "report_contract_refused")
            self.assertEqual(len(self.owner.state()["specialist_assessments"]), 0)
            self.assertEqual(len(self.active()), 1)

    def test_production_planner_consumes_actual_roster_snapshot_and_task_counter(self):
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            state = self.owner.state()
            result = workflow_planning.plan(state, self.path, self.document, self.progress(),
                                             ["reviewer"], config.load_config(self.configuration), self.now())
            self.assertEqual(set(result["assignments"]), {"reviewer"})
            self.assertNotEqual(result["assignments"]["reviewer"], result["worker_kinds"]["reviewer"])
            self.assertEqual(result["snapshot_ref"]["source"], str(self.path))
            self.assertTrue(result["tiers"]["reviewer"]["capability"])

    def select_backpressure(self, *, exceptions=None):
        configuration = json.loads(self.configuration.read_text())
        configuration["schema_version"] = 9
        configuration["backpressure"] = {"schema_version": 1,
            "global": {"in_flight": 1, "integration": 1}, "repositories": {},
            "exceptions": exceptions or [], "rationale": "Explicit isolated-fixture thresholds."}
        self.configuration.write_text(json.dumps(configuration))
        self.document["config"] = recovery.receipt(str(self.configuration))[0]

    def foreign_enrollment(self):
        supervision.enroll(self.path, {"id": "foreign", "agent": "elsewhere", "task": "two",
            "report": str(self.root / "foreign-report.md"), "pane_id": None, "native_session": None}, self.now())

    def test_saturated_new_start_waits_without_planning_or_native_effects(self):
        self.select_backpressure()
        self.admit()
        self.foreign_enrollment()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            before = self.path.read_bytes()
            events = list(self.native.events)
            with patch.object(runner, "planner", side_effect=AssertionError("Capacity waits before planning.")):
                result = runner.tick()
            self.assertEqual(result["data"]["status"], "waiting")
            self.assertEqual(result["data"]["reason"], "global_in_flight_limit")
            self.assertFalse(result["wake_agent"])
            self.assertEqual(self.native.events, events)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertIsNone(self.progress()["pending"])

    def test_full_capacity_does_not_deadlock_native_correction_review_and_release(self):
        self.select_backpressure()
        self.admit()
        with self.owner.session() as capability:
            runner = self.runner(capability)
            def deliver(job):
                blocking = job["role"] == "reviewer" and self.progress()["round"] == 0
                self.deliver(job, outcome="blocking" if blocking else None)
            self.advance(runner, lambda: self.progress()["phase"] == "merge", delivery=deliver)
            self.assertEqual([row["role"] for row in self.owner.state()["assignments"]],
                             ["developer", "reviewer", "developer", "reviewer", "release"])
            self.assertEqual(self.progress()["round"], 1)

    def test_expired_capacity_exception_waits_in_the_actual_owner(self):
        self.select_backpressure(exceptions=[{"task": "one", "until": "2026-10-18T00:00:00Z",
                                             "reason": "An expired fixture exception."}])
        self.admit()
        self.foreign_enrollment()
        with self.owner.session() as capability:
            result = self.runner(capability).tick()
            self.assertEqual(result["data"]["status"], "waiting")
            self.assertFalse(result["data"]["capacity"]["exception"]["active"])
            self.assertIsNone(self.progress()["pending"])

    def test_capacity_exception_cannot_bypass_exhausted_harnesses(self):
        self.select_backpressure(exceptions=[{"task": "one", "until": (self.origin + timedelta(days=1)).isoformat(),
                                             "reason": "An explicit fixture capacity exception."}])
        self.admit()
        self.foreign_enrollment()
        state = self.owner.state()
        add_snapshot(state, {"schema_version": 5, "measured_at": self.now(), "agents": {
            name: {"kind": name, "state": "idle", "headroom_pct": 0.0}
            for name in ("claude", "codex", "grok")}, "failed_agents": [], "skipped_agents": []})
        save_state(self.path, state)
        with self.owner.session() as capability:
            runner = self.runner(capability)
            events = list(self.native.events)
            with patch.object(runner, "planner", wraps=workflow_planning.plan) as planner:
                result = runner.tick()
            self.assertTrue(planner.called)
            self.assertEqual(result["data"]["status"], "exception")
            self.assertEqual(self.native.events, events)
            self.assertEqual(self.owner.state()["assignments"], [])
            self.assertIsNone(self.progress()["pending"])


if __name__ == "__main__":
    unittest.main()
