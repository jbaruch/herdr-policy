"""Native launch, input and report adapters for the admitted task owner.

The caller holds the primary owner transaction and a workflow_operation while
mutating. `changed` persists the caller's actual current job/intent; no adapter
creates a second journal. Native lifecycle, composer, tier and delivery checks
are shared with legacy rounds. Legacy task/fix bookkeeping is intentionally
absent from the transport call: the schema-2 task owner enforces those bounds.
No caller-provided environment or serialized capability is accepted.
"""

import json
import os
import subprocess
import time

from . import assign, config, lifecycle, members, recovery, report_delivery, report_gates, supervision, workflow_dispatch
from .errors import HerdrError, StateError, UsageError
from .herdr import error_code
from .launch import verify_running
from .workflow_workspace import REPORT_LIMIT, capture


class NativeWorkflowAdapter:
    def __init__(self, capability, client, state, changed, clock, *, sleeper=time.sleep, run=subprocess.run):
        from .progression_owner import ServiceCapability
        if not isinstance(capability, ServiceCapability) or client.context.mode != "native":
            raise UsageError("Use the actual admitted native task owner for workflow transport.", {})
        self.capability, self.client = capability, client
        self.state = state
        self.changed, self.clock, self.sleeper, self.run = changed, clock, sleeper, run

    def _identity(self, job, worker, *, adopt=False):
        live = self.client.agent_get(job["agent"])
        if live.get("pane_id") != job["pane_id"]:
            raise UsageError("The native job moved to another pane; reconcile its original assignment before progression.", {})
        native = report_delivery.native_identity(live)
        if job["native_session"] is not None and native != job["native_session"]:
            raise UsageError("The native job session changed; preserve its original report obligation and obtain owner recovery.", {})
        if native is not None and job["native_session"] is None:
            actual = verify_running(self.client, worker, job["pane_id"], job["tier"])
            prior = job["tier"].get("verified")
            if not isinstance(prior, dict) or prior.get("pid") != actual.get("pid"):
                raise UsageError("A later native session lacks this assignment's original launch process proof; do not adopt another worker's report.", {})
            if adopt:
                job["native_session"] = native
                supervision.refine(self.capability.state_path, job["id"], job["pane_id"], native, self.clock())
                self.changed()
        return native

    def launch(self, job, template, paths, history, *, worktree):
        """One fresh native assignment; retries must reconcile its durable job."""
        if job["role"] == "release":
            with report_gates.holding(self.capability.state_path):
                report_gates.require_no_verdict_gate(self.capability.state_path, self.capability.task,
                                                    self.state["recovery"]["dispatches"])
                progress = self.state["recovery"]["tasks"][self.capability.task]["progression"]
                supervised = supervision.load(self.capability.state_path)
                for identifier in progress["jobs"].values():
                    prior = workflow_dispatch.current_job(self.state, supervised, identifier)
                    report_gates.require_clear(self.capability.state_path, prior["report"], True)
                return self._launch(job, template, paths, history, worktree=worktree)
        return self._launch(job, template, paths, history, worktree=worktree)

    def _launch(self, job, template, paths, history, *, worktree):
        prepared = self.capability._prepared
        if (job["status"] != "prepared" or prepared is None or prepared.get("kind") != "workflow"
                or prepared.get("operation") != "apply"):
            raise UsageError("Reconcile this job's original native effect; it cannot be spawned again from a later state.", {})
        worker = config.assignment_worker(template, job["agent"])
        job["status"] = "starting"
        self.changed()
        def before_start(pane):
            job["pane_id"] = pane
            self.changed()
        pane = lifecycle.spawn(self.client, worker, job["tier"], cwd=worktree,
                               history=history, before_start=before_start, sleep=self.sleeper)
        job["pane_id"] = pane
        job["status"] = "ready"
        live = self.client.agent_get(worker.name)
        if live.get("pane_id") != pane:
            raise UsageError("The newly launched job lost its exact pane; preserve the startup outcome before another dispatch.", {})
        job["native_session"] = report_delivery.native_identity(live)
        job["tier"] = {**job["tier"], "verified": verify_running(self.client, worker, pane, job["tier"])}
        self.changed()
        supervision.enroll(self.capability.state_path, {"id": job["id"], "agent": worker.name,
            "task": self.capability.task, "report": job["report"], "pane_id": pane,
            "native_session": job["native_session"]}, self.clock())
        def observed(_step, observation):
            recovery.observe_reserved(self.state["recovery"], job["id"], observation)
            self.changed()
        def before_send(_step, observation):
            workflow_dispatch.sending(self.state, job["id"], observation, self.clock())
            job["status"] = "sending"
            job["transport"] = {"before_send": observation}
            self.changed()
        def recorded(raw):
            normalized = workflow_dispatch.finish(self.state, job["id"], raw)
            job["transport"] = normalized
            job["tier"] = raw["tier"]
            job["status"] = "running" if raw["status"] == "applied" else "not_sent" if raw["status"] == "not_sent" else "uncertain"
            self.changed()
        # The parent task owns its correction number, independence and scope.
        # task=None disables only the legacy round journal; native proof and
        # composer checks below execute unchanged under the owner's capability.
        result = assign.apply(self.client, {job["role"]: worker.name}, {worker.name: worker},
            {"common": paths["common"], job["role"]: job["brief"]}, self.clock(),
            task=None, fix_round=None, history=history, tiers={job["role"]: job["tier"]},
            reports={job["role"]: job["report"]}, fresh=True, assignment_scoped=True,
            on_prepare=observed, on_before_send=before_send, on_result=recorded, sleep=self.sleeper,
            contents={path: capture(path)[1] for path in (paths["common"], job["brief"])})
        self._identity(job, worker, adopt=True)
        return result

    def observe(self, job, template, task, worktree):
        """Canonical --once report wait; terminal stalls are never ordinary waits."""
        worker = config.assignment_worker(template, job["agent"])
        native = self._identity(job, worker)
        binary = self.client.context.executable
        environment = {**os.environ, "HERDR_BIN": binary, "FOREMAN_HERDR_BIN": binary}
        def run(argv, **kwargs):
            return self.run(argv, env=environment, timeout=90, **kwargs)
        try:
            checked, code = members.check(self.capability.state_path, job["id"], worktree, run=run)
        except (OSError, subprocess.TimeoutExpired):
            raise StateError("The canonical native report check failed; restore the current job's read-only evidence tools before deciding its outcome.", {}) from None
        if len(checked["wait"].encode("utf-8")) > 32768:
            raise StateError("The native report check exceeded its output budget; preserve the current assignment and inspect its evidence owner.", {})
        try:
            waited = json.loads(checked["wait"])
        except ValueError:
            raise StateError("The native report check returned invalid evidence; restore its matching installation before progression.", {}) from None
        if (not isinstance(waited, dict) or waited.get("agent") != job["agent"]
                or waited.get("report_path") != job["report"] or type(waited.get("found")) is not bool):
            raise StateError("The report checkpoint does not bind this native job and report; preserve the original obligation.", {})
        if self._identity(job, worker) != native:
            raise UsageError("Native identity changed during delivery observation; another session cannot settle this job.", {})
        if code == 0:
            if native is None:
                return {"state": "exception", "reason": "native_session_unconfirmed", "wait": waited}
            if waited["found"] is not True:
                raise StateError("A successful report check did not prove delivery; preserve its unknown outcome for owner recovery.", {})
            evidence, body = capture(job["report"], limit=REPORT_LIMIT)
            return {"state": "delivered", "wait": waited, "evidence": evidence, "body": body.decode("utf-8"), "native_session": native}
        if code == 1 and waited.get("reason") == "checkpoint_pending" and waited.get("stall") is None:
            return {"state": "waiting", "reason": "checkpoint_pending", "native_session": native}
        if code in (1, 3, 4, 5, 6):
            return {"state": "exception", "reason": waited.get("reason") or "native_wait_refused", "wait": waited}
        raise StateError("The canonical report checker failed; preserve the job and restore its tools before deciding delivery or retry.", {})

    def close(self, job, *, accepted):
        """Close only already validated native report bytes, using existing owners."""
        prepared = self.capability._prepared
        if prepared is None or prepared.get("kind") != "workflow" or prepared.get("operation") != "close":
            raise UsageError("Close native work through its current durable workflow intent.", {})
        captured, _body = capture(job["report"], limit=REPORT_LIMIT)
        if captured != job["report_evidence"] or job["claim"] is None:
            raise UsageError("Restore the actual validated report before closing its native assignment.", {})
        with report_gates.holding(self.capability.state_path):
            report_gates.require_clear(self.capability.state_path, job["report"], accepted)
            def same_native():
                try:
                    live = self.client.agent_get(job["agent"])
                except HerdrError as exc:
                    if error_code(exc) != "agent_not_found":
                        raise
                    return  # The lifecycle owner still proves pane absence/ownership.
                if live.get("pane_id") != job["pane_id"] or report_delivery.native_identity(live) != job["native_session"]:
                    raise UsageError("The native session changed after report delivery; preserve the replacement and reconcile the original close obligation.", {})
            closure = lifecycle.close(self.client, job["agent"], job["pane_id"],
                                      before_close=same_native, sleep=self.sleeper)
            outcome = "Workflow {}: {}".format(job["id"], "accepted" if accepted else "needs_work")
            drained = supervision.drain(self.capability.state_path)
            events = [event for event in drained["events"] if event["member"] == job["id"]]
            if events:
                supervision.acknowledge(self.capability.state_path, {"through": drained["through"], "outcomes": [
                    {"event": event["id"], "outcome": outcome, "evidence": [job["report"]]} for event in events]}, self.clock())
            supervision.resolve(self.capability.state_path, {"id": job["id"], "outcome": outcome,
                                                           "evidence": [job["report"]]}, self.clock())
        job["status"] = "closed"
        self.changed()
        return closure
