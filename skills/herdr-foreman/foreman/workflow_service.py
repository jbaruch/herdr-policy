"""Execute an admitted task through its existing native and evidence owners.

One current intent fences each effect. Native dispatches, assessments and
supervision retain their original authorities; the task stores references,
not another assignment history. Waiting/reading happens outside the primary
transaction. An unknown effect never becomes a new dispatch on restart.
"""

import json
import os
from pathlib import Path
import time
from typing import Callable

from . import cli, config, engagement, load_set, policy_paths, progression_owner as authority
from . import progression_runtime, recovery, report_delivery, report_gates, supervision
from . import workflow_contract as schema, workflow_dispatch as dispatch
from . import workflow_planning, workflow_workspace as workspace
from .errors import ForemanError, UsageError
from .progression_service import capture_contract
from .state import TransactionBusy, latest_snapshot, save_state, state_lock
from .workflow_native import NativeWorkflowAdapter


MEASUREMENT_MAX_AGE = 900


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class WorkflowService:
    def __init__(self, capability, client, *, clock=cli.now_iso, sleeper=time.sleep,
                 native: Callable[..., NativeWorkflowAdapter] = NativeWorkflowAdapter,
                 planner=workflow_planning.plan, release=None):
        if not isinstance(capability, authority.ServiceCapability):
            raise UsageError("Start task execution with its actual admitted service capability.", {})
        self.capability, self.client = capability, client
        self.clock, self.sleeper = clock, sleeper
        if release is None:
            from .workflow_release import WorkflowReleaseAdapter
            release = WorkflowReleaseAdapter()
        self.native, self.planner, self.release = native, planner, release
        state = authority._load(capability.state_path)
        capability.require_current(capability.state_path, state, capability.task)
        authority.verify_foreman(capability.state_path, client, native_only=True)
        grant = authority.current_grant(state, capability.task)
        assert grant is not None
        captured, self.document = capture_contract(grant["contract"]["path"])
        if captured != grant["contract"]:
            raise UsageError("Restore the admitted task workflow before running its owner.", {})
        self.profile = schema.contract(self.document, state["recovery"]["tasks"][capability.task])
        self.inputs = workspace.inputs(self.document)
        progress = state["recovery"]["tasks"][capability.task]["progression"]
        schema.validate_current(progress, self.document)
        shared = Path(progress["delivery"]["base_checkout"]) if progress["delivery"] is not None else workspace.base_checkout(self.document)
        policy = policy_paths.brief_inputs(Path(__file__).resolve().parents[1], shared,
            Path.home() / ".tessl", os.environ.get("HERDR_CODING_POLICY_ROOT") or None)
        self.policy = {key: policy[key] for key in ("POLICY_INDEX", "RELEASE_SKILL")}
        self.policy["TASK_WORKFLOW"] = str(Path(__file__).resolve().parents[1] / "references/task-workflow.md")
        self.policy["WORKFLOW_REVIEW"] = str(Path(__file__).resolve().parents[1] / "workflow-review.py")
        if not all(Path(self.policy[name]).is_file() for name in ("TASK_WORKFLOW", "WORKFLOW_REVIEW")):
            raise UsageError("Restore the co-shipped admitted task-workflow contract before starting its executor.", {})
        self.agents = config.parse_config(json.loads(self.inputs[self.document["config"]["path"]]))
        self.by_kind = {agent.name: agent for agent in self.agents}
        if not self.agents or any(not agent.assignment_scoped or not agent.tiers for agent in self.agents):
            raise UsageError("Configure fresh assignment-scoped workers and their tier tables before starting unattended work.", {})
        capability._workflow_executor = self

    @property
    def path(self):
        return self.capability.state_path

    def _current(self):
        state = authority._load(self.path)
        self.capability.require_current(self.path, state, self.capability.task)
        task = state["recovery"]["tasks"][self.capability.task]
        progress = task.get("progression")
        schema.validate_current(progress, self.document)
        if progress["generation"] != self.capability.generation:
            raise UsageError("Restore the current task generation before resuming its workflow.", {})
        workspace.inputs(self.document)
        return state, task, progress

    def _save(self, state):
        self.capability.lease.require_current()
        authority.verify_foreman(self.path, self.client, native_only=True)
        schema.validate_current(state["recovery"]["tasks"][self.capability.task]["progression"], self.document)
        save_state(self.path, state)

    def _view(self, progress, status, reason=None):
        return load_set._bounded({"schema_version": 2, "wake_agent": status == "exception", "data": {
            "task": self.capability.task, "generation": self.capability.generation,
            "status": status, "phase": progress["phase"], "correction": progress["round"],
            "jobs": progress["jobs"], "pending_intent": progress["pending"]["id"] if progress["pending"] else None,
            "reason": reason, "exception": progress["exception"],
            "exception_digest": supervision.digest(progress["exception"]) if progress["exception"] is not None else None,
            "delivery": progress["delivery"],
            "authorizes_acceptance": False, "authorizes_release": False}})

    def _exception(self, state, code, sources=(), actions=("inspect_current_evidence", "return_authority")):
        progress = state["recovery"]["tasks"][self.capability.task]["progression"]
        phase = progress["exception"]["phase"] if progress["phase"] == "exception" else progress["phase"]
        at = self.clock()
        occurrence = supervision.digest([self.capability.task, self.capability.generation, phase, at,
                                         len(state["recovery"]["events"])])
        progress.update(phase="exception", at=at, exception={
            "id": occurrence, "code": code, "phase": phase, "sources": list(dict.fromkeys(
                "".join(char if ord(char) >= 32 else " " for char in str(item)).encode("utf-8")[:4096].decode("utf-8", errors="ignore")
                for item in sources))[:8], "actions": list(actions)})
        self._save(state)
        return self._view(progress, "exception", code)

    def _intent(self, progress, operation, *, job=None, inputs=(), dispatches=()):
        identifier = "workflow-" + supervision.digest([self.capability.task, self.capability.generation,
            progress["round"], progress["phase"], operation, job["id"] if job else None])[:48]
        progress["pending"] = {"schema_version": 2, "id": identifier, "operation": operation,
            "argv": [], "inputs": list(inputs), "effects_started": False,
            "dispatches": list(dispatches), "job": job}

    def _before_effect(self, state):
        progress = state["recovery"]["tasks"][self.capability.task]["progression"]
        intent = progress["pending"]
        if intent is None:
            raise UsageError("Restore this task's durable effect intent before native transport.", {})
        for expected in intent["inputs"]:
            if workspace.capture(expected["path"])[0] != expected:
                raise UsageError("A pending effect's input changed; preserve its original obligation and reconcile before transport.", {})
        if not intent["effects_started"]:
            intent["effects_started"] = True
            self._save(state)

    def _roles(self, progress):
        if progress["phase"] == "implement":
            return ["developer"]
        if progress["phase"] == "verify":
            return ["reviewer"] + (["tester"] if self.profile["profile"] != "bounded" else [])
        if progress["phase"] == "release":
            return ["release"]
        return []

    def _brief(self, state, task, progress, role, report, identifier):
        template = self.inputs[self.document["briefs"][role]["path"]].decode("utf-8")
        reports = []
        if role in ("reviewer", "tester", "release"):
            supervised = supervision.load(self.path)
            for responsibility, prior_identifier in progress["jobs"].items():
                if responsibility not in (("developer", "reviewer", "tester") if role == "release" else ("developer",)):
                    continue
                prior = dispatch.current_job(state, supervised, prior_identifier)
                member = next(row for row in supervised["members"] if row["id"] == prior_identifier)
                receipt, _ = workspace.capture(prior["report"], limit=workspace.REPORT_LIMIT)
                if (prior["status"] != "closed" or member["resolution"] is None or not any(
                        item["path"] == receipt["path"] and item["sha256"] == receipt["sha256"]
                        for item in member["resolution"]["evidence"])):
                    raise UsageError("Restore the prior responsibility's closed, byte-bound report before dispatching its dependent work.", {})
                reports.append({"responsibility": responsibility, "report": receipt})
        dependencies = [*progress["blockers"], *(row["report"] for row in reports)]
        for expected in dependencies:
            if workspace.capture(expected["path"], limit=workspace.REPORT_LIMIT)[0] != expected:
                raise UsageError("Restore the current blocker and prerequisite report bytes before constructing their dependent assignment.", {})
        context = {"schema_version": 1, "task": task["task"], "scope": task["scope"],
            "authorization": task["authorization"], "base_revision": task["base_revision"],
            "allowed_paths": task["allowed_paths"], "repository": self.document["repository"],
            "head_revision": progress["head"]["commit"] if progress["head"] else None,
            "correction": progress["round"], "profile": self.profile["profile"],
            "responsibilities": schema.responsibilities(self.profile, role),
            "acceptance": self.document["acceptance"], "blocking_reports": progress["blockers"],
            "current_reports": reports,
            "publication": self.document["publication"], "effects": self.document["effects"],
            "review_evidence": str(Path(self.document["artifact_directory"]) / "reviews-{}.json".format(identifier.replace(":", "-"))) if role == "release" else None,
            "report": report}
        body = (template.rstrip() + "\n\n## Admitted current task\n\n```json\n" +
                json.dumps(context, indent=2, sort_keys=True) + "\n```\n\n" +
                "Deliver exactly one operative WORKFLOW JSON claim under the installed workflow report contract. "
                "Use the actual full current Git HEAD, the responsibilities above and this report path. "
                "Review/test outcomes also require exactly one VERDICT line. "
                "A blocked or uncertain result stays explicit; do not invent a passing check or change the admitted scope. "
                "The final chat line must match this marker exactly:\nREPORT: " + report + "\n").encode("utf-8")
        return body, dependencies

    def _make_job(self, state, task, progress, role, plan):
        root = workspace.prepare_directory(self.document["artifact_directory"])
        grant = authority.current_grant(state, task["task"])
        assert grant is not None
        header = {"schema_version": 2, "state": str(self.path), "task": task["task"],
                  "generation": progress["generation"], "contract": grant["contract"],
                  "policy_paths": self.policy}
        common_body = (self.inputs[self.document["common"]["path"]].rstrip() +
            b"\n\n## Admitted task owner\n\n```json\n" + encoded(header) + b"```\n\n" +
            b"This assignment belongs to the actual schema-2 owner above. Read POLICY_INDEX and TASK_WORKFLOW "
            b"from the absolute policy_paths. The release responsibility also reads RELEASE_SKILL in full and "
            b"runs its complete release flow through publication; the executor owns local task teardown. "
            b"Other roles read their current task inputs and role brief. No history-directory traversal or "
            b"legacy round paperwork is a normal-path prerequisite. Existing operator holds remain binding.\n")
        common, _ = workspace.write_current(root, "common.md", common_body)
        base = "workflow-" + supervision.digest([task["task"], progress["generation"], progress["round"], progress["phase"], progress["plan"]["sha256"]])[:48]
        identifier = base + ":" + role
        artifact = identifier.replace(":", "-")
        report = str(root / "report-{}.md".format(artifact))
        if Path(report).exists() or Path(report).is_symlink():
            raise UsageError("This unsent attempt already has report bytes; preserve them and reconcile rather than adopting or overwriting another result.", {})
        body, dependencies = self._brief(state, task, progress, role, report, identifier)
        brief, _ = workspace.write_current(root, "brief-{}.md".format(artifact), body, immutable=True)
        job = {"schema_version": 1, "id": identifier, "role": role,
            "agent": plan["assignments"][role], "worker_kind": plan["worker_kinds"][role],
            "tier": {key: value for key, value in plan["tiers"][role].items() if key not in cli.PLAN_ONLY_TIER_FIELDS},
            "status": "prepared", "pane_id": None, "native_session": None, "report": report,
            "brief": brief["path"], "at": self.clock(), "transport": None, "report_evidence": None, "claim": None}
        schema.validate_job(job)
        dispatch.reserve(state, task["task"], progress["generation"], progress["round"], job,
                         self.by_kind[job["worker_kind"]], common["path"], self.clock())
        self._intent(progress, "apply", job=job, inputs=[common, brief, progress["plan"], *dependencies], dispatches=[job["id"]])
        self._save(state)

    def _resume(self, state, task, progress):
        intent = progress["pending"]
        operation, job = intent["operation"], intent["job"]
        if operation == "cleanup":
            try:
                return self.release.resume_cleanup(self, state, task, progress)
            except ForemanError as exc:
                return self._exception(state, "cleanup_owner_refused", [intent["id"], exc.message],
                                       ("reconcile_original_effect", "return_authority"))
        if operation == "apply":
            row = next((row for row in state["recovery"]["dispatches"] if row["id"] == job["id"]), None)
            if row is not None and row["status"] == "applied":
                # Canonical readback wins over an interrupted launcher return.
                current = dispatch.current_job(state, supervision.load(self.path), job["id"])
                if any(current[key] != job[key] for key in ("id", "role", "agent", "report", "brief", "worker_kind")):
                    return self._exception(state, "dispatch_readback_conflict", [job["id"]])
                progress["jobs"][job["role"]] = job["id"]
                progress.update(pending=None, at=self.clock())
                self._save(state)
                return self._view(progress, "advanced")
        elif operation == "close":
            member = next((row for row in supervision.load(self.path)["members"] if row["id"] == job["id"]), None)
            if (member is not None and not member["active"] and member["resolution"] is not None
                    and job["report_evidence"] is not None
                    and any(row["path"] == job["report_evidence"]["path"] and row["sha256"] == job["report_evidence"]["sha256"]
                            for row in member["resolution"]["evidence"])):
                progress.update(pending=None, at=self.clock())
                self._save(state)
                return self._view(progress, "advanced")
        if intent["effects_started"]:
            return self._exception(state, "pending_effect_requires_reconciliation", [intent["id"]],
                                   ("reconcile_original_effect", "return_authority"))
        try:
            with self.capability.workflow_operation(state, operation, before_effect=lambda: self._before_effect(state)):
                client = self.capability.authorized_client(self.client)
                adapter = self.native(self.capability, client, state, lambda: self._save(state),
                                      self.clock, sleeper=self.sleeper)
                if operation == "apply":
                    common = str(Path(self.document["artifact_directory"]) / "common.md")
                    adapter.launch(job, self.by_kind[job["worker_kind"]], {"common": common}, state["assignments"],
                                   worktree=self.document["repository"]["worktree"])
                    # Do not trust adapter return/exit. Re-enter readback next tick.
                    return self._view(progress, "effect_recorded")
                if operation == "close":
                    adapter.close(job, accepted=job["claim"]["outcome"] in ("built", "verified", "ready", "delivered"))
                    return self._view(progress, "effect_recorded")
                if operation == "measure":
                    args = cli.build_parser().parse_args(["measure", "--config", self.document["config"]["path"],
                                                        "--state", str(self.path), "--now", self.clock()])
                    _result, error = cli.cmd_measure(args, client=client)
                    # The existing measurement owner saved its own fresh state.
                    state, task, progress = self._current()
                    if error is not None:
                        return self._exception(state, "measurement_incomplete", [str(self.path)])
                    progress.update(pending=None, at=self.clock())
                    self._save(state)
                    return self._view(progress, "advanced")
                raise UsageError("Restore the supported original task effect before resuming progression.", {})
        except ForemanError as exc:
            # Preserve every callback checkpoint and uncertain native effect.
            return self._exception(state, "native_owner_refused", [intent["id"], exc.message],
                                   ("reconcile_original_effect", "return_authority"))

    @staticmethod
    def _stamp(member):
        return supervision.digest({"assignment": supervision.expected_assignment(member),
                                   "active": member["active"], "resolution": member["resolution"]})

    def _independent(self, state, job, jobs):
        if job["role"] not in ("reviewer", "tester"):
            return
        for other in jobs:
            if other["id"] == job["id"]:
                continue
            if other["role"] not in ("developer", "reviewer", "tester"):
                continue
            if (other["agent"] == job["agent"] or other["pane_id"] == job["pane_id"]
                    or other["native_session"] is not None and other["native_session"] == job["native_session"]):
                raise UsageError("Independent verification shares an implementation or verification native identity; preserve the reports and obtain a fresh independent responsibility.", {})
        contributors = composition_contributors(state, self.capability.task)
        if job["agent"] in contributors:
            raise UsageError("This verifier contributed to the task; preserve its excluding history and dispatch independent verification.", {})

    def _record_delivery(self, state, progress, job, observed, head):
        if workspace.capture(job["report"], limit=workspace.REPORT_LIMIT)[0] != observed["evidence"]:
            raise UsageError("The delivered report changed during observation; preserve its original bytes before deciding this attempt.", {})
        if progress["head"] is not None and job["role"] != "developer" and head != progress["head"]:
            raise UsageError("The implementation changed during independent verification or release; obtain current-tip evidence before progression.", {})
        live = self.client.agent_get(job["agent"])
        if (live.get("pane_id") != job["pane_id"]
                or report_delivery.native_identity(live) != observed["native_session"]):
            raise UsageError("The native report owner changed before assessment; preserve the original session's obligation.", {})
        if job["native_session"] is None:
            supervision.refine(self.path, job["id"], job["pane_id"], observed["native_session"], self.clock())
            job["native_session"] = observed["native_session"]
        root = workspace.prepare_directory(self.document["artifact_directory"])
        delivery_name = "delivery-{}.json".format(job["id"].replace(":", "-"))
        if (root / delivery_name).exists():
            delivery, prior = workspace.capture(root / delivery_name)
            try:
                waited = json.loads(prior)
            except ValueError:
                raise UsageError("Restore this job's original successful delivery receipt before assessment.", {}) from None
            if (not isinstance(waited, dict) or waited.get("found") is not True
                    or waited.get("agent") != job["agent"] or waited.get("report_path") != job["report"]):
                raise UsageError("The preserved delivery receipt belongs to another outcome; retain it for owner reconciliation.", {})
        else:
            delivery, _ = workspace.write_current(root, delivery_name, encoded(observed["wait"]), immutable=True)
        # This event is backed by the canonical native delivery checker, never
        # by a file's existence or the worker's claim alone.
        def observed_event(current):
            member = next(row for row in current["members"] if row["id"] == job["id"])
            detail = {"present": True, **observed["evidence"], "size": len(observed["body"].encode("utf-8"))}
            if member["observed"].get("report") != detail:
                supervision.append_event(current, self.clock(), job["id"], "report_observed", detail)
                member["observed"]["report"] = detail
        supervision.transaction(self.path, observed_event)
        if job["role"] in ("reviewer", "tester"):
            engagement.record_assessment(state, self.path, {"id": job["id"], "dispatch": job["id"],
                "report": job["report"], "delivery": delivery["path"]}, self.clock())
            engagement.require_accepted(state, job["id"], job["report"])
        # Record additive contribution evidence even when the later workflow
        # claim is malformed. A format failure cannot erase independence facts.
        claim = schema.claim(observed["body"], self.capability.task, job["role"], self.profile,
                             head["commit"], self.document["acceptance"]["criteria"])
        if job["role"] == "developer" and claim["outcome"] == "built" and not head["paths"]:
            raise UsageError("No authorized implementation change is present; reconcile the task's actual outcome instead of accepting an empty built claim.", {})
        job.update(report_evidence=observed["evidence"], claim=claim, status="delivered")
        if job["role"] in ("reviewer", "tester"):
            if claim["outcome"] != "verified":
                report_gates.record_verdict(self.path, job["report"], job["report_evidence"]["sha256"],
                                            job["id"], self.clock())
            if job["role"] == "reviewer":
                recovery.record_report(state["recovery"], {"dispatch": progress["jobs"]["developer"],
                    "head_revision": head["commit"], "verdict": "approved" if claim["outcome"] == "verified" else "blocking",
                    "review_mode": "full", "reviewer": job["agent"], "report": job["report"],
                    "changed_paths": head["paths"]}, self.clock())
        if job["role"] == "developer" and claim["outcome"] == "built":
            progress["head"] = head
        self._intent(progress, "close", job=job, inputs=[observed["evidence"], delivery], dispatches=[job["id"]])
        progress["at"] = self.clock()
        self._save(state)

    def _route(self, state, task, progress, jobs, head):
        claims, receipts = {}, {}
        supervised = supervision.load(self.path)
        for job in jobs:
            if job["role"] not in self._roles(progress):
                continue
            receipt, body = workspace.capture(job["report"], limit=workspace.REPORT_LIMIT)
            member = next(row for row in supervised["members"] if row["id"] == job["id"])
            if (job["status"] != "closed" or member["resolution"] is None or not any(
                    item["path"] == receipt["path"] and item["sha256"] == receipt["sha256"]
                    for item in member["resolution"]["evidence"])):
                raise UsageError("Restore the closed assignment's byte-bound report before routing its outcome or correction inputs.", {})
            claims[job["role"]] = schema.claim(body.decode(), task["task"], job["role"], self.profile,
                head["commit"], self.document["acceptance"]["criteria"])
            receipts[job["role"]] = receipt
        if any(claim["outcome"] == "blocked" for claim in claims.values()):
            return self._exception(state, "worker_blocked", [job["report"] for job in jobs if job["role"] in claims])
        if head != progress["head"]:
            return self._exception(state, "verified_head_changed", [self.document["repository"]["worktree"]])
        if progress["phase"] == "implement":
            progress.update(phase="verify", plan=None, at=self.clock())
        elif progress["phase"] in ("verify", "release"):
            routes = [schema.workflow_profiles.correction_route({"schema_version": 1,
                "authority_current": True, "evidence_current": True, **claim["correction"]}, claim["findings"])
                for claim in claims.values() if claim["correction"] is not None]
            if any(route["action"] == "decision_packet" for route in routes):
                return self._exception(state, "verification_decision_required", [job["report"] for job in jobs if job["role"] in claims],
                                       ("resolve_task_decision", "return_authority"))
            if any(claim["outcome"] == "blocking" for claim in claims.values()):
                if progress["round"] >= recovery.DEFAULT_FIX_LIMIT:
                    return self._exception(state, "correction_allowance_exhausted", [job["report"] for job in jobs if job["role"] in claims],
                                           ("diagnose_task", "return_authority"))
                blockers = [receipts[job["role"]]
                            for job in jobs if job["role"] in claims and claims[job["role"]]["outcome"] == "blocking"]
                progress.update(phase="implement", round=progress["round"] + 1, jobs={}, plan=None,
                                blockers=blockers, at=self.clock())
            elif progress["phase"] == "verify":
                # Re-checks clear only the same responsibility's actual verdict
                # gates, through the existing evidence owner.
                for job in jobs:
                    if job["role"] not in claims:
                        continue
                    gated = report_gates.open_verdict_gates(self.path, task["task"], state["recovery"]["dispatches"])
                    for gate in gated:
                        gated_dispatch = next(row for row in state["recovery"]["dispatches"] if row["id"] == gate["dispatch"])
                        if gated_dispatch["role"] == job["role"]:
                            report_gates.resolve(self.path, gate["report"], "clear", "Independent current-tip workflow re-check.",
                                self.clock(), report_gates.ledger_view(self.path, None), evidence=job["report"])
                report_gates.require_no_verdict_gate(self.path, task["task"], state["recovery"]["dispatches"])
                progress.update(phase="release", plan=None, blockers=[], at=self.clock())
            elif claims["release"]["outcome"] == "ready":
                # Preparation is settled, but its immutable report cannot
                # become delivery. Continue with a fresh release assignment.
                progress["jobs"].pop("release")
                progress.update(plan=None, at=self.clock())
            else:
                progress.update(phase="merge", plan=None, at=self.clock(), delivery={
                    "schema_version": 1, "pull_request": claims["release"]["pull_request"],
                    "merge_commit": None, "publisher_run": None, "tag": None, "tessl_version": None,
                    "tessl_confirmed": False, "acr_confirmed": False, "accepted": False,
                    "base_checkout": str(workspace.base_checkout(self.document)), "cleanup_step": 0})
        self._save(state)
        return self._view(progress, "advanced")

    def tick(self):
        authority.verify_foreman(self.path, self.client, native_only=True)
        try:
            return self._tick()
        except TransactionBusy:
            return load_set._bounded({"schema_version": 2, "wake_agent": False, "data": {
                "task": self.capability.task, "generation": self.capability.generation,
                "status": "waiting", "reason": "owner_transaction_busy",
                "authorizes_acceptance": False, "authorizes_release": False}})
        except ForemanError as exc:
            with state_lock(self.path):
                state, _task, _progress = self._current()
                return self._exception(state, "workflow_owner_refused", [exc.message],
                                       ("inspect_current_evidence", "return_authority"))

    def _tick(self):
        if (getattr(getattr(self.client, "context", None), "mode", None) != "native"
                or not os.environ.get("HERDR_ENV")):
            raise UsageError("Run the task owner in its actual connected native environment; saved state never supplies HERDR_ENV.", {})
        progression_runtime.pulse(self.capability, self.clock())
        stamp = ""
        with state_lock(self.path):
            state, task, progress = self._current()
            if progress["phase"] in ("exception", "complete"):
                return self._view(progress, progress["phase"])
            if progress["pending"] is not None:
                return self._resume(state, task, progress)
            if self.profile["specialist_domains"]:
                return self._exception(state, "specialist_evidence_required", self.profile["specialist_domains"],
                                       ("admit_specialist_evidence", "return_authority"))
            roles = self._roles(progress)
            if not roles:
                stamp = supervision.digest(progress)
                release_observation = True
            else:
                release_observation = False
        if release_observation:
            # Review/publication helpers own their waits. Their potentially
            # long reads cannot retain another task's primary transaction.
            try:
                observed = self.release.observe(self, state, task, progress)
            except ForemanError as exc:
                with state_lock(self.path):
                    state, task, progress = self._current()
                    return self._exception(state, "release_evidence_unconfirmed", [exc.message],
                                           ("reconcile_release_evidence", "return_authority"))
            with state_lock(self.path):
                state, task, progress = self._current()
                if supervision.digest(progress) != stamp:
                    return self._view(progress, "waiting", "release_observation_superseded")
                try:
                    return self.release.commit(self, state, task, progress, observed)
                except ForemanError as exc:
                    return self._exception(state, "release_evidence_unconfirmed", [exc.message],
                                           ("reconcile_release_evidence", "return_authority"))
        with state_lock(self.path):
            state, task, progress = self._current()
            roles = self._roles(progress)
            missing = [role for role in roles if role not in progress["jobs"]]
            if missing:
                if progress["plan"] is None:
                    snapshot = latest_snapshot(state)
                    age = None if snapshot is None else (supervision.timestamp(self.clock()) -
                        supervision.timestamp(snapshot["measured_at"])).total_seconds()
                    if age is None or not 0 <= age <= MEASUREMENT_MAX_AGE:
                        self._intent(progress, "measure", inputs=[self.document["config"]])
                        self._save(state)
                        return self._view(progress, "prepared")
                    plan = self.planner(state, self.path, self.document, progress, roles, self.agents, self.clock())
                    progress["plan"], _ = workspace.write_current(self.document["artifact_directory"], "plan.json", encoded(plan))
                    self._save(state)
                captured, body = workspace.capture(progress["plan"]["path"])
                if captured != progress["plan"]:
                    return self._exception(state, "current_plan_changed", [captured["path"]])
                self._make_job(state, task, progress, missing[0], json.loads(body))
                return self._view(progress, "prepared")
            supervised = supervision.load(self.path)
            jobs = [dispatch.current_job(state, supervised, identifier) for identifier in progress["jobs"].values()]
            for job in jobs:
                self._independent(state, job, jobs)
            active = [job for job in jobs if job["role"] in roles and job["status"] != "closed"]
            if not active:
                # All current source checks happen again before the transition.
                head = workspace.inspect(self.document, task)
                try:
                    return self._route(state, task, progress, jobs, head)
                except ForemanError as exc:
                    return self._exception(state, "evidence_owner_refused", [exc.message])
            expected_progress = supervision.digest(progress)
            stamps = {job["id"]: self._stamp(next(row for row in supervised["members"] if row["id"] == job["id"])) for job in active}
        # Never hold the primary task lock while waiting for native completion.
        adapter = self.native(self.capability, self.client, state, lambda: None, self.clock, sleeper=self.sleeper)
        for job in active:
            observed = adapter.observe(job, self.by_kind[job["worker_kind"]], task,
                                       self.document["repository"]["worktree"])
            if observed["state"] == "waiting":
                continue
            with state_lock(self.path):
                state, task, progress = self._current()
                current = next(row for row in supervision.load(self.path)["members"] if row["id"] == job["id"])
                if supervision.digest(progress) != expected_progress or self._stamp(current) != stamps[job["id"]]:
                    return self._view(progress, "waiting", "observation_superseded")
                if observed["state"] != "delivered":
                    return self._exception(state, "native_delivery_exception", [job["report"], observed["reason"]],
                                           ("reconcile_original_effect", "return_authority"))
                try:
                    head = workspace.inspect(self.document, task, built=job["role"] != "developer")
                    self._record_delivery(state, progress, job, observed, head)
                except ForemanError as exc:
                    return self._exception(state, "report_contract_refused", [job["report"], exc.message])
                return self._view(progress, "prepared")
        return self._view(progress, "waiting", "native_work_in_progress")


def composition_contributors(state, task):
    """Actual native contributors, including declared contributions on failed reports."""
    contributors = {row["agent"] for row in state["recovery"]["dispatches"]
                    if row["task"] == task and row["role"] == "developer" and row["status"] != "not_sent"}
    contributors.update(row["agent"] for row in state["specialist_assessments"]
                        if row["task"] == task and row["contribution"] in engagement.EXCLUDING_CONTRIBUTIONS)
    return contributors
