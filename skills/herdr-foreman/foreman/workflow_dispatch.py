"""Map workflow transport to the existing canonical dispatch/assignment owners.

The workflow record retains only current phase/dispatch references and a live
pending intent. Native results live in recovery.dispatches and assignments,
where existing reconciliation, counters, refusal recovery and metrics find
them. No second dispatch log or Markdown assessment ledger is written here.
"""

from copy import deepcopy

from . import model_unavailability, recovery, supervision
from .errors import UsageError
from .state import add_assignment


def reserve(state, task, generation, round_number, job, template, common, at):
    paths = {"common": common, job["role"]: job["brief"]}
    identifier, fingerprint = recovery.dispatch_identity(task, job["role"], job["agent"], round_number or None,
        paths, supplied=job["id"].rsplit(":", 1)[0], options={"workflow_schema": 2,
            "generation": generation, "report": job["report"], "model": job["tier"]["model"],
            "effort": job["tier"].get("effort")})
    if identifier != job["id"]:
        raise UsageError("Use the workflow's original role-bound dispatch intent; a different identity cannot reserve this job.", {})
    record = {"id": identifier, "fingerprint": supervision.report_bound_fingerprint(fingerprint, job["report"]),
        "role": job["role"], "agent": job["agent"], "task": task, "fix_round": round_number or None,
        "plan": None, "work": None, "common": common, "brief": job["brief"],
        "brief_identity": recovery.brief_identity(paths, job["role"], job["report"]),
        "provider": template.kind, "worker_kind": template.name,
        "launch_scope": model_unavailability.launch_scope(template)}
    if job["role"] == "reviewer":
        record["reviewer_scope"] = "verification"
    return recovery.reserve(state["recovery"], record, at)


def sending(state, identifier, observation, at):
    """The input boundary calls this before the actual assignment prompt."""
    return recovery.mark_sending(state["recovery"], identifier, at, deepcopy(observation))


def finish(state, identifier, raw):
    """Associate actual native evidence with the task already owning this intent.

    assign.apply's transport-only call does not own legacy task metadata. The
    canonical reservation supplies task/fix/account identity; model, clear,
    process, pane, send and start evidence come unchanged from the transport.
    """
    store = state["recovery"]
    dispatch = next((row for row in store["dispatches"] if row["id"] == identifier), None)
    if dispatch is None or raw.get("role") != dispatch["role"] or raw.get("agent") != dispatch["agent"]:
        raise UsageError("Native result differs from the reserved workflow role/worker; preserve its uncertain effect.", {})
    if dispatch["status"] == "applied":
        prior = dispatch["result"]
        if prior["pane_id"] != raw.get("pane_id") or prior["tier"] != raw.get("tier"):
            raise UsageError("An existing dispatch already carries different native evidence; reconcile it without another send.", {})
        return prior
    result = {**deepcopy(raw), "task": dispatch["task"], "fix_round": dispatch["fix_round"],
              "dispatch_id": identifier, "assignment_scoped": True, "worker_kind": dispatch["worker_kind"],
              "launch_scope": deepcopy(dispatch["launch_scope"])}
    if dispatch["role"] == "reviewer":
        result["reviewer_scope"] = dispatch["reviewer_scope"]
    else:
        result.pop("reviewer_scope", None)
    add_assignment(state, result["at"], result["role"], result["agent"], status=result["status"],
                   task=dispatch["task"], fix_round=dispatch["fix_round"],
                   reviewer_scope=result.get("reviewer_scope"), cleared=result["cleared"],
                   clear_reason=result["clear_reason"], context_session=result.get("context_session"), tier=result["tier"])
    recovery.finish_dispatch(store, identifier, result, len(state["assignments"]) - 1, result["at"])
    return dispatch["result"]


def current_job(state, supervised, identifier):
    """A derived current view; canonical native facts are not copied into progression."""
    dispatch = next((row for row in state["recovery"]["dispatches"] if row["id"] == identifier), None)
    member = next((row for row in supervised["members"] if row["id"] == identifier), None)
    if dispatch is None or member is None or dispatch["status"] != "applied" or dispatch["result"] is None:
        raise UsageError("Restore this workflow job's canonical applied dispatch and enrollment before observation.", {})
    expected = supervision.expected_assignment(member)
    result = dispatch["result"]
    if expected["task"] != dispatch["task"] or expected["agent"] != dispatch["agent"]:
        raise UsageError("The current native enrollment does not belong to its task dispatch; preserve both owners' evidence.", {})
    return {"schema_version": 1, "id": identifier, "role": dispatch["role"], "agent": dispatch["agent"],
        "worker_kind": dispatch["worker_kind"], "tier": deepcopy(result["tier"]),
        "status": "closed" if not member["active"] else "running", "pane_id": expected["pane_id"],
        "native_session": expected["native_session"], "report": expected["report"],
        "brief": dispatch["brief"], "at": result["at"], "transport": deepcopy(result),
        "report_evidence": None, "claim": None}
