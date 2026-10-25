"""Current workflow preparation decisions shared by execution and inspection.

These checks read current owners and inputs without reserving a worker,
writing a plan or authorizing an effect. The executor retains its live lease,
native-context verification and final effect-boundary checks.
"""

import json
import os
from pathlib import Path
from typing import Any

from . import config, policy_paths, progression_owner as authority, supervision
from . import context_output, progression_runtime, recovery
from . import workflow_capacity, workflow_contract, workflow_dispatch, workflow_planning
from . import workflow_workspace as workspace
from .errors import ForemanError, PlanError, UsageError
from .progression_service import capture_contract
from .state import latest_snapshot


MEASUREMENT_MAX_AGE = workflow_planning.MEASUREMENT_MAX_AGE


def current_inputs(state, state_path, task_name, supervised, policy_root, *, policy_identity=None) -> dict[str, Any]:
    """Read the same pinned task inputs used by the executing owner; no lease claim."""
    grant = authority.current_grant(state, task_name)
    if grant is None or grant["mode"] != "service" or grant.get("contract_schema", 1) != 2:
        raise UsageError("Admit the registered task through its verified owner before native execution.",
                         {"reason": "task_not_admitted"})
    version, digest = policy_identity if policy_identity is not None else authority.loaded_policy(policy_root)
    if grant["policy"] != {"version": version, "digest": digest}:
        raise UsageError("The loaded policy differs from this task's grant; preserve it for its verified handoff.",
                         {"reason": "policy_changed"})
    if authority._binding(supervised) != grant["binding"]:
        raise UsageError("The current supervision binding differs from the task's owner; preserve its grant.",
                         {"reason": "binding_changed"})
    if authority._unresumed_hold(supervised):
        raise UsageError("Preserve the current operator hold and its resume condition before task execution.",
                         {"reason": "operator_hold"})
    captured, document = capture_contract(grant["contract"]["path"])
    if captured != grant["contract"]:
        raise UsageError("Restore the admitted task workflow before running its owner.",
                         {"reason": "contract_changed"})
    task = state["recovery"]["tasks"][task_name]
    profile = workflow_contract.contract(document, task)
    progress = task.get("progression")
    workflow_contract.validate_current(progress, document)
    if progress["generation"] != grant["generation"]:
        raise UsageError("Restore the current task generation before resuming its workflow.",
                         {"reason": "generation_changed"})
    if authority.has_unowned_enrollments(state, supervised, task_name):
        raise UsageError("Reconcile this task's enrollment through its recorded dispatch owner before selecting more work.",
                         {"reason": "enrollment_owner_unverified"})
    inputs = workspace.inputs(document)
    shared = Path(progress["delivery"]["base_checkout"]) if progress["delivery"] is not None else workspace.base_checkout(document)
    skill_root = Path(__file__).resolve().parents[1]
    selected = policy_paths.brief_inputs(skill_root, shared, Path.home() / ".tessl",
        os.environ.get("HERDR_CODING_POLICY_ROOT") or None, workflow=True)
    policy = {key: selected[key] for key in ("POLICY_INDEX", "RELEASE_SKILL")}
    policy.update(TASK_WORKFLOW=str(skill_root / "references/workflow-worker.md"),
                  WORKFLOW_REVIEW=str(skill_root / "workflow-review.py"))
    if not all(Path(policy[name]).is_file() for name in ("TASK_WORKFLOW", "WORKFLOW_REVIEW")):
        raise UsageError("Restore the co-shipped admitted task-workflow contract before starting its executor.", {})
    try:
        configuration = json.loads(inputs[document["config"]["path"]])
    except (ValueError, UnicodeDecodeError):
        raise UsageError("Restore the pinned workflow configuration as valid UTF-8 JSON before execution.",
                         {"reason": "configuration_unreadable"}) from None
    agents = config.parse_config(configuration)
    if not agents or any(not agent.assignment_scoped or not agent.tiers for agent in agents):
        raise UsageError("Configure fresh assignment-scoped workers and their tier tables before starting unattended work.", {})
    return {"document": document, "profile": profile, "inputs": inputs, "policy": policy,
            "agents": agents, "backpressure": workflow_capacity.parse_policy(configuration),
            "by_kind": {agent.name: agent for agent in agents}}


def dependencies(state, supervised, document, progress, role):
    """Current byte-bound prerequisites, shared by the preview and compiled brief."""
    head = workspace.inspect(document, state["recovery"]["tasks"][document["task"]], built=role != "developer")
    if role != "developer" and head != progress["head"]:
        raise UsageError("The writer changed after the prerequisite source was accepted; preserve the changed head for its owner.",
                         {"reason": "current_head_changed"})
    reports = []
    if role in ("reviewer", "tester", "release"):
        for responsibility, identifier in progress["jobs"].items():
            if responsibility not in (("developer", "reviewer", "tester") if role == "release" else ("developer",)):
                continue
            prior = workflow_dispatch.current_job(state, supervised, identifier)
            member = next(row for row in supervised["members"] if row["id"] == identifier)
            receipt, _ = workspace.capture(prior["report"], limit=workspace.REPORT_LIMIT)
            if (prior["status"] != "closed" or member["resolution"] is None or not any(
                    item["path"] == receipt["path"] and item["sha256"] == receipt["sha256"]
                    for item in member["resolution"]["evidence"])):
                raise UsageError("Restore the prior responsibility's closed, byte-bound report before dispatching its dependent work.",
                                 {"reason": "prerequisite_delivery_unconfirmed"})
            reports.append({"responsibility": responsibility, "report": receipt})
    required = [*progress["blockers"], *(row["report"] for row in reports)]
    for expected in required:
        if workspace.capture(expected["path"], limit=workspace.REPORT_LIMIT)[0] != expected:
            raise UsageError("Restore the current blocker and prerequisite report bytes before constructing their dependent assignment.",
                             {"reason": "prerequisite_changed"})
    return reports, required


def roles(profile, progress):
    if progress["phase"] == "implement":
        return ["developer"]
    if progress["phase"] == "verify":
        return ["reviewer"] + (["tester"] if profile["profile"] != "bounded" else [])
    if progress["phase"] == "release":
        return ["release"]
    return []


def capacity_family(state, task):
    from . import progression_owner as authority, workflow_contract
    grant = authority.current_grant(state, task)
    if grant is not None and grant.get("contract_schema", 1) == 2:
        try:
            captured, document = capture_contract(grant["contract"]["path"])
            if captured != grant["contract"]:
                return None
            workflow_contract.contract(document, state["recovery"]["tasks"][task])
            return document["repository"]["github"]
        except ForemanError:
            return None
    return None


def preparation(state, supervised, state_path, document, progress, selected_roles,
                agents, policy, at, *, planner=workflow_planning.plan) -> dict[str, Any]:
    """One current decision; its result never grants dispatch authority."""
    missing = [role for role in selected_roles if role not in progress["jobs"]]
    if not missing:
        raise UsageError("Inspect the current jobs before requesting another worker assignment.",
                         {"reason": "current_jobs_require_observation"})
    dependencies(state, supervised, document, progress, missing[0])
    capacity = None
    if policy is not None:
        capacity = workflow_capacity.evaluate(state, supervised, document["task"],
            document["repository"]["github"], policy, at,
            family=lambda task: capacity_family(state, task))
        if not capacity["allowed"]:
            return {"state": "capacity_wait", "capacity": capacity, "plan": None}
    if progress["plan"] is None:
        snapshot = latest_snapshot(state)
        age = None if snapshot is None else (supervision.timestamp(at) -
            supervision.timestamp(snapshot["measured_at"])).total_seconds()
        if age is None or not 0 <= age <= MEASUREMENT_MAX_AGE:
            return {"state": "measurement_required", "capacity": capacity, "plan": None}
        plan = planner(state, state_path, document, progress, selected_roles, agents, at)
        return {"state": "plan_ready", "capacity": capacity, "plan": plan}
    return {"state": "plan_recorded", "capacity": capacity, "plan": None}


def read_plan(receipt, selected_roles, templates):
    """The same pinned plan reader is used before previewing or preparing a job."""
    captured, raw = workspace.capture(receipt["path"])
    if captured != receipt:
        raise UsageError("Restore the owner's unchanged current plan before preparing another job.",
                         {"reason": "recorded_plan_changed"})
    try:
        plan = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise UsageError("Restore the current plan as its original JSON document before preparing another job.",
                         {"reason": "recorded_plan_unreadable"}) from None
    if (not isinstance(plan, dict) or any(not isinstance(plan.get(key), dict)
                                         for key in ("assignments", "worker_kinds", "tiers"))
            or any(not isinstance(plan["assignments"].get(role), str) or not plan["assignments"][role]
                   or not isinstance(plan["worker_kinds"].get(role), str)
                   or plan["worker_kinds"].get(role) not in templates
                   or not isinstance(plan["tiers"].get(role), dict)
                   or not isinstance(plan["tiers"][role].get("model"), str)
                   for role in selected_roles)):
        raise UsageError("Restore the current plan's original assignments, worker kinds and tiers.",
                         {"reason": "recorded_plan_invalid"})
    return plan


def _item(task, ready, dispatchable, reason, **facts):
    return {"task": task, "ready": ready, "dispatchable": dispatchable,
            "reason": reason, **facts}


def assess(state, state_path, supervised, task_name, at, policy_root, *, native_verified,
           policy_identity=None, planner=workflow_planning.plan, health=progression_runtime.health):
    """Observe one task without minting a capability or consuming a worker."""
    if task_name not in state["recovery"]["tasks"]:
        return _item(task_name, None, None, "task_not_registered")
    try:
        current = current_inputs(state, state_path, task_name, supervised, policy_root,
                                 policy_identity=policy_identity)
    except ForemanError as exc:
        reason = exc.details.get("reason", "workflow_inputs_unverified")
        contradicted = reason in {"policy_changed", "binding_changed", "operator_hold",
                                   "contract_changed", "generation_changed", "enrollment_owner_unverified"}
        return _item(task_name, False if contradicted else None, False if contradicted else None,
                     reason, error=exc.code)
    document, profile = current["document"], current["profile"]
    progress = state["recovery"]["tasks"][task_name]["progression"]
    facts = {"generation": progress["generation"], "phase": progress["phase"],
             "repository": document["repository"]["github"]}
    if progress["phase"] == "exception":
        return _item(task_name, False, False, "task_exception", **facts,
                     exception=progress["exception"]["code"])
    if progress["phase"] == "complete":
        return _item(task_name, False, False, "task_complete", **facts)
    if progress["pending"] is not None:
        return _item(task_name, False, False, "pending_intent", **facts,
                     operation=progress["pending"]["operation"])
    selected_roles = roles(profile, progress)
    if not selected_roles:
        return _item(task_name, None, False, "release_readback_required", **facts)
    missing = [role for role in selected_roles if role not in progress["jobs"]]
    if not missing:
        return _item(task_name, False, False, "current_jobs_require_observation", **facts)
    if profile["specialist_domains"]:
        return _item(task_name, False, False, "specialist_evidence_required", **facts)
    facts["responsibility"] = missing[0]
    try:
        decision = preparation(state, supervised, state_path, document, progress, selected_roles,
            current["agents"], current["backpressure"], at, planner=planner)
    except ForemanError as exc:
        reason = exc.details.get("reason")
        if reason is not None:
            return _item(task_name, reason == "quota_exhausted", False, reason, **facts, error=exc.code)
        planned = isinstance(exc, PlanError)
        return _item(task_name, True if planned else None, False if planned else None,
                     "worker_selection_failed" if planned else "preparation_unverified",
                     **facts, error=exc.code)
    if decision["state"] == "capacity_wait":
        return _item(task_name, True, False, decision["capacity"]["reason"],
                     **facts, capacity=decision["capacity"])
    if decision["state"] == "measurement_required":
        return _item(task_name, True, None, "measurement_required", **facts)
    plan = decision["plan"]
    if decision["state"] == "plan_recorded":
        try:
            plan = read_plan(progress["plan"], missing, current["by_kind"])
        except ForemanError as exc:
            reason = exc.details.get("reason", "recorded_plan_unreadable")
            return _item(task_name, True, False if reason != "recorded_plan_unreadable" else None,
                         reason, **facts)
    if (not isinstance(plan, dict) or not isinstance(plan.get("worker_kinds"), dict)
            or any(not isinstance(plan["worker_kinds"].get(role), str)
                   or plan["worker_kinds"].get(role) not in current["by_kind"] for role in missing)):
        return _item(task_name, True, False, "recorded_plan_invalid", **facts)
    remaining = workflow_planning.quota(state, plan["worker_kinds"][missing[0]], at)
    if remaining is None:
        return _item(task_name, True, None, "quota_unmeasured", **facts)
    if remaining <= 0:
        return _item(task_name, True, False, "quota_exhausted", **facts)
    live = health(state, supervised, task_name, at)
    if live["state"] != "live":
        return _item(task_name, True, None, "executor_health_unverified", **facts, executor=live["state"])
    if not native_verified:
        return _item(task_name, True, None, "native_foreman_unverified", **facts)
    return _item(task_name, True, True, "preparation_ready", **facts,
                 worker_kind=plan["worker_kinds"][missing[0]],
                 capacity=decision["capacity"])


def counts(items):
    """These counts cover only the returned records, never unseen tasks."""
    return {"ready": sum(row["ready"] is True for row in items),
            "not_ready": sum(row["ready"] is False for row in items),
            "readiness_unmeasured": sum(row["ready"] is None for row in items),
            "dispatchable": sum(row["dispatchable"] is True for row in items),
            "excluded_ready": sum(row["ready"] is True and row["dispatchable"] is False for row in items),
            "dispatchability_unmeasured_ready": sum(row["ready"] is True and row["dispatchable"] is None for row in items)}


def view(state, state_path, supervised, at, policy_root, *, task=None,
         limit=context_output.DEFAULT_LIMIT, offset=0, native_verified=False,
         native_reason="native_context_unavailable", planner=workflow_planning.plan,
         health=progression_runtime.health):
    """A bounded current page; no saved view, source copy or dispatch lease."""
    context_output.validate_page(limit, offset)
    supervision.timestamp(at)
    unfinished, _integration = workflow_capacity.work_sets(state, supervised)
    candidates = set(state["recovery"]["tasks"]) | {name for name in unfinished if isinstance(name, str) and name}
    open_tasks = []
    for name in sorted(candidates):
        try:
            closed = recovery.task_closure(state["recovery"], state["assignments"], name)
        except UsageError:
            closed = None
        if name in unfinished or closed is None:
            open_tasks.append(name)
    if task is not None:
        if task not in open_tasks:
            raise UsageError("Select an open canonical task from its owner; a missing or completed task is not an empty readiness result.", {})
        open_tasks = [task]
    identity = authority.loaded_policy(policy_root)
    selected = open_tasks[offset:offset + limit]
    rows = [assess(state, state_path, supervised, name, at, policy_root,
                   native_verified=native_verified, policy_identity=identity, planner=planner, health=health)
            for name in selected]

    def build(effective):
        items = rows[:effective]
        pagination = context_output.page(open_tasks, offset, effective)
        pagination.pop("items")
        return {"observed_at": at, "native_foreman": {"verified": native_verified,
                                                    "reason": "verified" if native_verified else native_reason},
                "counts_scope": "returned_items", "counts": counts(items), "items": items, "pagination": pagination,
                "unexamined_in_response": len(open_tasks) - len(items),
                "context_complete": len(open_tasks) == len(items),
                "authorizes_dispatch": False}

    return context_output.fit_pages(build, limit, offset)
