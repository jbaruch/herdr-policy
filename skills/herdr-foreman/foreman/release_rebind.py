"""Settled schema-2 release handoff without replaying verification.

The private Git checkout intent retains the previous grant/progress and the
replacement immutable contract. Existing grant/progress schemas remain exact;
the grant generation changes, while all historical owner records stay put.
Adopted workflows retain their original transfer proof through the versioned
Git-owner source-scope bridge; neither contract nor adoption gains new fields.
"""

from copy import deepcopy

from . import engagement, progression_owner as authority, report_gates, release_activation, supervision
from . import workflow_adoption, workflow_contract as schema, workflow_dispatch
from . import workflow_readiness, workflow_workspace as workspace
from .errors import UsageError
from .progression_service import capture_contract
from .state import save_state


def prepare(state_path, state, supervised, task, source, target, head, plugin_root, *, recorded=False):
    grant = authority.current_grant(state, task)
    if grant is None or grant["mode"] != "service":
        return None, None
    if grant.get("contract_schema") not in (2, 3):
        raise UsageError("This task's prepared workflow has no supported settled release-path handoff. Preserve its source scope and finish through its existing owner; do not re-admit it as new work.",
                         {"reason": "release_checkout_source_scope_unsupported", "authorizes_release": False})
    if grant["contract_schema"] == 3 and not recorded:
        release_activation.require("adopted task release-checkout handoff")
    current = workflow_readiness.current_inputs(state, state_path, task, supervised, plugin_root)
    document, profile = current["document"], current["profile"]
    progress = state["recovery"]["tasks"][task]["progression"]
    phase = progress["exception"]["phase"] if progress["phase"] == "exception" else progress["phase"]
    if (document["repository"]["worktree"] != str(source) or phase != "release"
            or progress["pending"] is not None or progress["delivery"] is not None
            or progress["head"] is None or progress["head"]["commit"] != head
            or progress["blockers"] or "release" in progress["jobs"]):
        raise UsageError("Prepare a successor only before release transport, at this task's settled independently verified head. Preserve active effects, release reports, blockers and publication obligations through their existing owner.", {})
    if progress["exception"] is not None and progress["exception"]["code"] != "workflow_owner_refused":
        raise UsageError("Preserve this task's unresolved decision. A clean checkout can restore Git inspection; it cannot settle another release or worker exception.", {})
    required = {"developer", "reviewer"} | ({"tester"} if profile["profile"] != "bounded" else set())
    if set(progress["jobs"]) != required:
        raise UsageError("Retain all original implementation and independent verification jobs before the release handoff; missing coverage stays unknown.", {})
    from .workflow_service import composition_contributors
    contributors = composition_contributors(state, task)
    jobs, evidence = [], []
    for role, identifier in progress["jobs"].items():
        job = workflow_dispatch.current_job(state, supervised, identifier)
        member = next(row for row in supervised["members"] if row["id"] == identifier)
        captured, body = workspace.capture(job["report"], limit=workspace.REPORT_LIMIT)
        adopted = document.get("adoption") is not None and identifier == document["adoption"]["dispatch"]
        if adopted:
            qualified = workflow_adoption.dependencies(state_path, state, supervised, document) == captured
        else:
            claim = schema.claim(body.decode(), task, role, profile, head, document["acceptance"]["criteria"])
            qualified = claim["outcome"] == ("built" if role == "developer" else "verified")
        if (job["role"] != role or job["status"] != "closed" or member["resolution"] is None
                or not qualified
                or not any(row["path"] == captured["path"] and row["sha256"] == captured["sha256"]
                           for row in member["resolution"]["evidence"])):
            raise UsageError("Restore the original closed, byte-bound built/verified report for every responsibility before release handoff.", {})
        dispatch = next(row for row in state["recovery"]["dispatches"] if row["id"] == identifier)
        workflow_adoption.brief_evidence(dispatch, supervision.expected_assignment(member))
        workflow_adoption.source_scope(document, dispatch)
        engagement.require_accepted(state, identifier, job["report"])
        report_gates.require_clear(state_path, job["report"], True)
        jobs.append(job)
        evidence.append(captured)
    for job in jobs:
        if job["role"] == "developer":
            continue
        if job["agent"] in contributors or any(other["id"] != job["id"] and (
                other["agent"] == job["agent"] or other["pane_id"] == job["pane_id"]
                or other["native_session"] is not None and other["native_session"] == job["native_session"])
                for other in jobs):
            raise UsageError("Preserve contributor exclusions and actual independent native identities before release handoff.", {})
    report_gates.require_no_verdict_gate(state_path, task, state["recovery"]["dispatches"])
    replacement = deepcopy(document)
    replacement["repository"]["worktree"] = str(target)
    schema.contract(replacement, state["recovery"]["tasks"][task])
    return {"kind": "workflow", "grant": deepcopy(grant), "progress": deepcopy(progress),
            "reports": evidence}, replacement


def expected_grant(evidence, captured, at):
    grant = deepcopy(evidence["grant"])
    grant.update(generation=grant["generation"] + 1, contract=captured, at=at)
    authority.validate_grant(grant)
    return grant


def commit(state_path, state, intent):
    evidence = intent["evidence"]
    if evidence["kind"] != "workflow":
        return None
    captured, document = capture_contract(evidence["successor"]["path"])
    if captured != evidence["successor"]:
        raise UsageError("Restore the immutable successor contract before completing the recorded handoff.", {})
    row = state["recovery"]["tasks"][intent["task"]]
    original, declaration = capture_contract(evidence["grant"]["contract"]["path"])
    replacement = deepcopy(declaration)
    replacement["repository"]["worktree"] = intent["path"]
    if original != evidence["grant"]["contract"] or document != replacement:
        raise UsageError("The successor contract must change only the selected checkout path; retain original authority, inputs and publication scope.", {})
    grant = expected_grant(evidence, captured, intent["at"])
    if row["authority"] == grant:
        return grant["generation"]
    if row["authority"] != evidence["grant"] or row["progression"] != evidence["progress"]:
        raise UsageError("Task authority or current progress changed after the checkout intent. Preserve both and reconcile that original handoff instead of overwriting the newer owner.", {})
    progress = deepcopy(evidence["progress"])
    # Keep the exact decision packet until its existing resume owner rechecks
    # the restored checkout. The helper does not waive a saved exception.
    progress.update(generation=grant["generation"], plan=None, at=intent["at"])
    schema.validate_current(progress, document)
    row.update(authority=grant, progression=progress)
    save_state(state_path, state)
    return grant["generation"]
