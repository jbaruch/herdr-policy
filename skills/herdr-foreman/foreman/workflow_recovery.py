"""Explicit recovery by the verified foreman, with no native effects.

The caller holds the canonical state lock. Recovery preserves the admitted
task, generation and cumulative correction counter. A free process lease
proves only exclusion; native no-send and close outcomes come from their
existing owners. Replaying a record never repeats a transport operation.
"""

from copy import deepcopy
import json
from pathlib import Path

from . import progression_owner as authority, recovery, supervision
from . import workflow_contract as schema, workflow_workspace as workspace
from .errors import UsageError
from .process_lease import process_lease
from .state import save_state


RETRYABLE = frozenset({"release_evidence_unconfirmed", "cleanup_owner_refused",
    "workflow_owner_refused", "evidence_owner_refused", "current_plan_changed",
    "native_owner_refused", "pending_effect_requires_reconciliation"})


def _replayed(state, data, kind):
    return any(row["kind"] == kind and row["task"] == data["task"] and row["details"] == data
               for row in state["recovery"]["events"])


def _commit(path, state, grant, supervised, data, at, kind, change):
    def commit(current):
        if authority._binding(current) != authority._binding(supervised) or authority._binding(current) != grant["binding"]:
            raise UsageError("Restore this task's admitted foreman binding before recovery; recovery cannot transfer authority.", {})
        with process_lease(grant["lease_path"]):
            change(current)
            recovery._event(state["recovery"], at, kind, data["task"], deepcopy(data))
            save_state(path, state)
        return {"task": data["task"], "replayed": False, "authorizes_dispatch": False}
    return supervision.transaction(path, commit)


def reconcile_not_sent(path, state, grant, supervised, document, data, at):
    """Retire exactly an owner-proved unsent launch; plan a fresh identity later."""
    progress = state["recovery"]["tasks"][data["task"]]["progression"]
    schema.validate_current(progress, document)
    intent = progress["pending"]
    if intent is None or intent["id"] != data["intent"] or intent["operation"] != "apply":
        raise UsageError("Reconcile only this task's current native launch intent; other effects need their own readback.", {})
    expected = set(intent["dispatches"])
    rows = {row["id"]: row for row in state["recovery"]["dispatches"] if row["id"] in expected}
    if (not expected or set(rows) != expected or any(row["task"] != data["task"] or row["status"] != "not_sent" for row in rows.values())
            or any(any(row["id"].startswith(base + ":transport-retry-") for base in expected) for row in state["recovery"]["dispatches"])):
        raise UsageError("Every expected dispatch must be owner-proved not_sent; process exit and a free lease prove no send outcome.", {})
    job = intent["job"]
    if job is None or job["id"] not in expected or Path(job["report"]).exists() or Path(job["report"]).is_symlink():
        raise UsageError("Preserve any existing report and the original native obligation before reconciling an unsent launch.", {})
    workspace.inputs(document)
    def change(current):
        authority._settled(state, current, data["task"])
        phase = progress["exception"]["phase"] if progress["phase"] == "exception" else progress["phase"]
        progress.update(phase=phase, exception=None, pending=None, plan=None, at=at)
        schema.validate_current(progress, document)
    return _commit(path, state, grant, supervised, data, at, "progression_intent_reconciled", change)


def resume(path, data, at, client, plugin_root):
    """Retry restored observations or independently proved effects, never decisions."""
    if (not isinstance(data, dict) or set(data) != {"task", "expected_generation", "exception", "authorization"}
            or len(json.dumps(data).encode("utf-8")) > authority.GRANT_BYTES):
        raise UsageError("Supply task, current generation, exact exception digest and explicit resume authorization.", {})
    recovery.text(data["task"], "task")
    recovery.authorization(data["authorization"])
    supervision.timestamp(at)
    state = authority._load(path)
    grant = authority.current_grant(state, data["task"])
    if (grant is None or grant["mode"] != "service" or grant.get("contract_schema") != 2
            or type(data["expected_generation"]) is not int or data["expected_generation"] != grant["generation"]):
        raise UsageError("Resume only the current admitted task-workflow generation.", {})
    supervised = authority.verify_foreman(path, client)
    version, digest = authority.loaded_policy(plugin_root)
    if grant["policy"] != {"version": version, "digest": digest}:
        raise UsageError("Restore the admitted policy bytes before resuming this task; recovery cannot adopt a different policy.", {})
    from .progression_service import capture_contract
    captured, document = capture_contract(grant["contract"]["path"])
    if captured != grant["contract"]:
        raise UsageError("Restore the admitted contract before resuming its task.", {})
    progress = recovery.task_record(state["recovery"], data["task"])["progression"]
    schema.validate_current(progress, document)
    if progress["phase"] != "exception":
        if _replayed(state, data, "progression_exception_resumed"):
            return {"task": data["task"], "replayed": True, "authorizes_dispatch": False}
        raise UsageError("No matching current task exception exists to resume.", {})
    packet = progress["exception"]
    if data["exception"] != supervision.digest(packet) or packet["code"] not in RETRYABLE:
        raise UsageError("Resume only the exact retryable current packet; disputes, scope changes and exhausted corrections require their decision owner.", {})
    workspace.inputs(document)
    intent = progress["pending"]
    if intent is not None and intent["effects_started"] and intent["operation"] != "cleanup":
        job = intent["job"]
        proved = False
        if job is not None and intent["operation"] == "apply":
            proved = any(row["id"] == job["id"] and row["task"] == data["task"] and row["status"] == "applied"
                         for row in state["recovery"]["dispatches"])
        elif job is not None and intent["operation"] == "close":
            proved = any(row["id"] == job["id"] and not row["active"] and row["resolution"] is not None
                and job["report_evidence"] is not None and any(
                    item["path"] == job["report_evidence"]["path"] and item["sha256"] == job["report_evidence"]["sha256"]
                    for item in row["resolution"]["evidence"]) for row in supervised["members"])
        if not proved:
            raise UsageError("Preserve the unknown native effect; resume requires canonical applied/closed evidence or separate no-send reconciliation.", {})
    def change(current):
        if authority._unresumed_hold(current):
            raise UsageError("The operator hold remains effective; this command never resumes a hold.", {})
        progress.update(phase=packet["phase"], exception=None, at=at)
        schema.validate_current(progress, document)
    return _commit(path, state, grant, supervised, data, at, "progression_exception_resumed", change)
