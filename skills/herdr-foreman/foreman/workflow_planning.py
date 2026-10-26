"""Select fresh workflow workers through the existing budget/tier planner.

The schema-2 owner supplies the real task, counter and canonical history.
Legacy correction-plan metadata is not fabricated to satisfy another loop.
No native worker is contacted and no source or owner record is written here.
"""

from . import capabilities, composition, lifecycle, planner, selection, recovery
from . import cli
from .chronology import timestamp
from .errors import PlanError, UsageError
from .state import latest_snapshot, role_counts


MEASUREMENT_MAX_AGE = 900


def quota(state, worker_kind, at):
    """Observed roster headroom, never a guarantee that a provider will accept input."""
    snapshot = latest_snapshot(state)
    if snapshot is None:
        return None
    age = (timestamp(at, "Quota checkpoint") - timestamp(snapshot["measured_at"], "Roster measurement")).total_seconds()
    if not 0 <= age <= MEASUREMENT_MAX_AGE:
        return None
    remaining = cli._snapshot_headroom(snapshot)
    value = remaining.get(worker_kind)
    groups = planner._window_groups(snapshot.get("agents", {}))
    group = groups.get(worker_kind)
    if group is not None:
        shared = [reading for name, reading in remaining.items() if groups.get(name) == group and reading is not None]
        if shared:
            value = min(shared)
    return value


def require_headroom(state, worker_kind, at):
    """Preserve a known exhausted account at preparation and native launch."""
    remaining = quota(state, worker_kind, at)
    if remaining is not None and remaining <= 0:
        raise UsageError("This workflow worker has no measured headroom; preserve its current account evidence before launching it.",
                         {"reason": "quota_exhausted", "worker_kind": worker_kind})


def correction_authority(state, task, round_number, role):
    """Use the actual cumulative allowance and its existing bounded work owner."""
    store = state["recovery"]
    progress = store["tasks"][task].get("progression", {})
    plan = None
    work = None
    if round_number and round_number > recovery.ceiling_at(store, task, round_number):
        plans = [row for row in recovery.active_plans(store) if row["task"] == task
                 and row["first_fix"] <= round_number <= row["last_fix"]]
        if len(plans) != 1:
            raise UsageError("Restore the unique existing correction authorization for this cumulative attempt.", {})
        plan = plans[0]["id"]
        from . import report_contract, workflow_workspace
        findings = []
        for expected in progress.get("blockers", []):
            receipt, body = workflow_workspace.capture(expected["path"])
            if receipt != expected:
                raise UsageError("Restore the exact blocking report before spending its approved correction allowance.", {})
            claim = report_contract.workflow_claim(body.decode("utf-8"))
            findings.extend(item["id"] for item in claim["findings"] if item["severity"] == "blocking" and item["status"] != "resolved")
        # Verifiers and release preserve the actual implementation plan/work
        # already recorded on the current developer dispatch.
        if role != "developer":
            source = next((row for row in store["dispatches"] if row["id"] == progress.get("jobs", {}).get("developer")), None)
            if source is None:
                raise UsageError("Restore the current developer's actual correction-work authorization before verification.", {})
            plan, work = source["plan"], source["work"]
        else:
            head = progress.get("head")
            work = {"base_revision": store["tasks"][task]["base_revision"], "scope": plans[0]["scope"],
                    "paths": head["paths"] if head is not None else [], "findings": sorted(set(findings))}
    recovery.validate_work(store, state["assignments"], task, round_number or None, plan, work,
                           implementation=role == "developer")
    return plan, work


def plan(state, state_path, document, progress, roles, agents, at):
    snapshot = latest_snapshot(state)
    if snapshot is None:
        raise UsageError("Measure the admitted worker roster before selecting workflow assignments.", {})
    if not agents or any(not agent.assignment_scoped or not agent.tiers for agent in agents):
        raise UsageError("Configure fresh assignment-scoped workers with verified tier tables before admitting background work.", {})
    constraints = composition.selection_constraints(roles, agents, {}, state["assignments"], document["task"],
        dispatches=state["recovery"]["dispatches"], assessments=state["specialist_assessments"],
        candidate_names=snapshot.get("agents", {}).keys())
    holds = cli._seat_holds(roles, document["task"], state, state_path)
    # This planner selects configured worker kinds, not existing native aliases.
    # Assignment/session independence is still checked by the native job owner.
    roster = {agent.name for agent in agents}
    excluded = {role: sorted((set(constraints["exclude"].get(role, [])) | set(holds["exclude"].get(role, []))) & roster)
                for role in roles}
    exhausted = {agent.name for agent in agents if (remaining := quota(state, agent.name, at)) is not None and remaining <= 0}
    for role in roles:
        eligible = roster - set(excluded[role])
        if eligible and eligible <= exhausted:
            raise PlanError("The eligible workflow workers have no measured headroom; preserve their current account evidence before selecting another assignment.",
                            {"reason": "quota_exhausted", "responsibility": role})
        excluded[role] = sorted(set(excluded[role]) | exhausted)
    table = capabilities.load(state_path)
    refusals = []
    rounds = {}
    candidates = cli._candidate_tiers(roles, agents, rounds, progress["round"] or None,
        excludes=excluded, headroom=cli._snapshot_headroom(snapshot), table=table,
        refusals=refusals, reusable_agents=True, measured_at=snapshot.get("measured_at"),
        at=at, capacity_groups=cli._snapshot_groups(snapshot), unavailable_store=state["recovery"])
    result = cli._build_plan_with_refusals(planner.plan, refusals, roles, snapshot,
        role_counts(state, cli._worker_kind_provenance(state)), exclude=excluded,
        operator_exclude={},
        role_costs=cli.load_role_costs(document["config"]["path"]),
        snapshot_ref={"source": str(state_path), "measured_at": snapshot.get("measured_at")},
        tier_candidates=candidates, rounds=rounds, familiarity=constraints["familiarity"],
        selection_rationale=constraints["rationale"] + holds["rationale"],
        roster=[agent.name for agent in agents], reusable_agents=True)
    result["selection"] = selection.records(result["assignments"], result.get("tiers"),
        {agent.name: agent for agent in agents}, {}, rounds, progress["round"] or None, table)
    result.update(schema_version=planner.ASSIGNMENT_PLAN_SCHEMA_VERSION,
                  worker_kinds=dict(result["assignments"]))
    result["assignments"] = lifecycle.identities(result["assignments"])
    return result
