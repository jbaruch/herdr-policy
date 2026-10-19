"""Current task-executor liveness in the existing supervision owner.

Schema-2 watcher rows are written only by a live ServiceCapability. A task has
one current row; restart replaces it under the existing owner locks. Pulses
update that row, never append events, reports, logs or another task database.
Legacy foreground watchers remain schema 1 and keep their existing contract.

The row grants nothing by itself. Continuation needs the current task grant,
unchanged policy/contract/binding, the live kernel lease and exact OS process.
Missing or stale proof refuses delegation without reclaiming task authority.
"""

from datetime import timedelta
from contextlib import contextmanager
import os
from pathlib import Path
import threading

from . import progression_owner as authority, supervision, supervision_runtime
from .errors import StateError, UsageError
from .errors import ForemanError
from .diagnostics import stderr_warn
from .process_lease import held, owned_by, validate_proof
from .state import TransactionBusy, state_lock


SCHEMA_VERSION = 2
PULSE_SECONDS = 15
LIVE_GRACE_SECONDS = 120
FIELDS = frozenset({"schema_version", "id", "at", "heartbeat", "deadline", "process", "status",
                    "reason", "ended_at", "task", "generation", "service_id", "lease_path", "policy", "binding", "lease_proof"})


def validate(row):
    if (not isinstance(row, dict) or set(row) != FIELDS or type(row["schema_version"]) is not int
            or row["schema_version"] != SCHEMA_VERSION or row["status"] not in ("running", "stopped")
            or not isinstance(row["task"], str) or not 0 < len(row["task"].encode()) <= authority.TASK_BYTES
            or type(row["generation"]) is not int or row["generation"] < 1
            or not isinstance(row["service_id"], str) or authority.IDENTIFIER.fullmatch(row["service_id"]) is None
            or not isinstance(row["lease_path"], str) or not Path(row["lease_path"]).is_absolute()
            or not isinstance(row["process"], dict) or set(row["process"]) != {"pid", "identity"}
            or type(row["process"]["pid"]) is not int or row["process"]["pid"] <= 0):
        raise UsageError("Restore the supported current task-executor liveness row before transferring supervision.", {})
    supervision.text(row["id"], "executor watcher identity")
    supervision.text(row["process"]["identity"], "executor process identity")
    for key in ("at", "heartbeat", "deadline"):
        supervision.timestamp(row[key])
    if row["reason"] is not None:
        supervision.text(row["reason"], "executor stop reason")
        if len(row["reason"].encode()) > 256:
            raise UsageError("Keep executor health reasons bounded; retrieve the task's current exception for details.", {})
    if (row["status"] == "running") != (row["ended_at"] is None):
        raise UsageError("Restore matching executor status and stop time; a stopped process supplies no continuation.", {})
    if row["ended_at"] is not None:
        supervision.timestamp(row["ended_at"])
    authority.validate_policy_binding(row["policy"], row["binding"])
    validate_proof(row["lease_proof"])


def pulse(capability, at, *, stopped=False, reason=None, probe=supervision_runtime.process_identity):
    """Publish this actual capability's current process, under root -> sidecar locks."""
    if not isinstance(capability, authority.ServiceCapability):
        raise UsageError("Only the admitted live executor can publish its process proof.", {})
    supervision.timestamp(at)
    process = probe(os.getpid())
    if process is None:
        raise StateError("Cannot prove this executor's OS identity; restore process visibility before delegating observation.", {})
    with state_lock(capability.state_path):
        state = authority._load(capability.state_path)
        capability.require_current(capability.state_path, state, capability.task)
        grant = authority.current_grant(state, capability.task)
        assert grant is not None
        if grant.get("contract_schema") == 2:
            from .workflow_service import WorkflowService
            executor = capability._workflow_executor
            if not isinstance(executor, WorkflowService) or executor.capability is not capability:
                raise UsageError("Initialize the actual admitted task executor before publishing its continuation; a lease or passive monitor alone is insufficient.", {})
            authority.verify_foreman(capability.state_path, executor.client, native_only=True)
        row = {"schema_version": SCHEMA_VERSION,
               "id": "executor-" + supervision.digest([capability.task, capability.generation]),
               "at": at, "heartbeat": at,
               "deadline": (supervision.timestamp(at) + timedelta(seconds=LIVE_GRACE_SECONDS)).isoformat(),
               "process": process, "status": "stopped" if stopped else "running", "reason": reason,
               "lease_proof": capability.lease.proof(),
               "ended_at": at if stopped else None, "task": capability.task,
               **{key: grant[key] for key in ("generation", "service_id", "lease_path", "policy", "binding")}}
        validate(row)
        def commit(data):
            capability.lease.require_current()
            if authority._binding(data) != grant["binding"] or authority._unresumed_hold(data):
                raise UsageError("A changed binding or operator hold prevents delegated observation; preserve its existing owner.", {})
            matches = [item for item in data["watchers"] if item["schema_version"] == 2 and item["task"] == capability.task]
            if len(matches) > 1:
                raise StateError("Multiple current executor rows exist for this task; reconcile their owner instead of replacing evidence.", {})
            if matches:
                if matches[0]["process"] == process and matches[0]["generation"] == capability.generation:
                    row["at"] = matches[0]["at"]
                matches[0].clear()
                matches[0].update(row)
            else:
                data["watchers"].append(row)
            return row
        return supervision.transaction(capability.state_path, commit)


def health(state, data, task, at, *, probe=supervision_runtime.process_identity):
    """Current owned continuation or an explicit non-live state; never an effect permit."""
    grant = authority.current_grant(state, task)
    if grant is None or grant["mode"] != "service":
        return {"state": "not_delegated"}
    rows = [row for row in data["watchers"] if row["schema_version"] == 2 and row["task"] == task]
    if len(rows) != 1:
        return {"state": "missing" if not rows else "conflicting"}
    row = rows[0]
    validate(row)
    if row["status"] != "running":
        return {"state": "stopped"}
    if any(row[key] != grant[key] for key in ("generation", "service_id", "lease_path", "policy", "binding")):
        return {"state": "superseded"}
    if authority._binding(data) != grant["binding"] or authority._unresumed_hold(data):
        return {"state": "held_or_rebound"}
    age = (supervision.timestamp(at) - supervision.timestamp(row["heartbeat"])).total_seconds()
    if age < 0 or age > LIVE_GRACE_SECONDS or supervision.timestamp(at) > supervision.timestamp(row["deadline"]):
        return {"state": "unresponsive"}
    if not held(grant["lease_path"]):
        return {"state": "lease_free"}
    if probe(row["process"]["pid"]) != row["process"]:
        return {"state": "process_lost"}
    if not owned_by(grant["lease_path"], row["process"]["pid"], row["lease_proof"]):
        return {"state": "lease_owner_unproved"}
    return {"state": "live", "generation": grant["generation"], "service_id": grant["service_id"]}


@contextmanager
def keep_alive(capability, clock):
    """Pulse during existing owners' long reads, without a history/log process."""
    stop = threading.Event()
    failures = []
    pulse(capability, clock())
    def beat():
        busy_ticks = 0
        while not stop.wait(PULSE_SECONDS):
            try:
                pulse(capability, clock())
                busy_ticks = 0
            except TransactionBusy as exc:
                busy_ticks += 1
                if busy_ticks * PULSE_SECONDS < LIVE_GRACE_SECONDS:
                    continue
                failures.append(exc)
                return
            except ForemanError as exc:
                failures.append(exc)
                return
    def require_healthy():
        if failures:
            raise StateError("The executor's current liveness proof failed; preserve its task and restore its original owner before further effects.", {}) from failures[0]
    thread = threading.Thread(target=beat, name="herdr-task-liveness", daemon=True)
    thread.start()
    try:
        yield require_healthy
    finally:
        stop.set()
        thread.join(timeout=1)
        if not thread.is_alive():
            try:
                pulse(capability, clock(), stopped=True, reason="executor_returned")
            except ForemanError as exc:
                # No stale row can remain a continuation after its actual
                # kernel resource closes. Never regain changed authority to
                # publish a cosmetic final pulse.
                stderr_warn("The task executor returned but its final liveness update was refused: {} Its closed kernel lease supplies no continuation.".format(exc.message))
        else:
            stderr_warn("The task executor's liveness update is still finishing; lease closure invalidates continuation. Inspect its actual saved owner state before a replacement.")


def continuation(state_path, data, at, plugin_root, *, probe=supervision_runtime.process_identity):
    """Current task obligations and exact members covered by their actual executor.

    Prepared schema-1 chains cannot transfer Stop obligations. A schema-2
    workflow must be implemented and admitted before its process can cover work.
    Unknown or unreadable proof covers nothing and remains visible to Stop.
    """
    from .progression_service import capture_contract
    from . import workflow_contract
    # Legacy owner stores cannot contain the new admitted contract type. Do
    # not migrate/read their historical sources merely to check native Stop.
    raw = supervision.read_json(state_path)
    if raw is None and any(row["schema_version"] == 2 for row in data["watchers"]):
        raise StateError("Restore the missing primary task owner before Stop; retained task-executor evidence cannot be treated as an empty legacy store.", {})
    recovery = raw.get("recovery", {}) if isinstance(raw, dict) else {}
    rows = recovery.get("tasks", {}) if isinstance(recovery, dict) else {}
    if not isinstance(rows, dict) or not any(
            isinstance(row, dict) and isinstance(row.get("authority"), dict)
            and row["authority"].get("mode") == "service"
            and (row["authority"].get("schema_version") != 1 or row["authority"].get("contract_schema") == 2)
            for row in rows.values()):
        return {"members": set(), "tasks": {}}
    state = authority._load(state_path)
    candidates = {task: metadata for task, metadata in state["recovery"]["tasks"].items()
                  if metadata.get("authority", {}).get("mode") == "service"
                  and metadata["authority"].get("contract_schema") == 2}
    if not candidates:
        return {"members": set(), "tasks": {}}
    version, digest = authority.loaded_policy(plugin_root)
    covered = set()
    tasks = {}
    for task, metadata in candidates.items():
        grant = metadata["authority"]
        progress = metadata.get("progression")
        if not isinstance(progress, dict) or progress.get("schema_version") != 2:
            tasks[task] = "current_progress_missing"
            continue
        if progress["phase"] == "complete":
            from .recovery import task_closure
            closed = task_closure(state["recovery"], state["assignments"], task)
            if (closed is None or closed["details"]["outcome"] != "merged"
                    or progress["delivery"] is None or not progress["delivery"]["accepted"]
                    or progress["delivery"]["cleanup_step"] != 5 or progress["pending"] is not None):
                tasks[task] = "accepted_closure_unproved"
            continue
        tasks[task] = "policy_changed"
        if grant["policy"] != {"version": version, "digest": digest}:
            continue
        tasks[task] = health(state, data, task, at, probe=probe)["state"]
        if tasks[task] != "live":
            continue
        captured, contract = capture_contract(grant["contract"]["path"])
        if captured != grant["contract"] or not isinstance(contract, dict) or contract.get("schema_version") != 2:
            tasks[task] = "contract_changed"
            continue
        workflow_contract.contract(contract, metadata)
        workflow_contract.validate_current(progress, contract)
        if progress["phase"] == "exception":
            tasks[task] = "task_exception"
            continue
        identifiers = set(progress["jobs"].values())
        pending = progress["pending"]
        if pending is not None and pending["effects_started"]:
            job = pending["job"]
            if pending["operation"] == "apply" and job is not None:
                applied = next((row for row in state["recovery"]["dispatches"] if row["id"] == job["id"]), None)
                if applied is None or applied["status"] != "applied":
                    tasks[task] = "native_effect_unsettled"
                    continue
                identifiers.add(job["id"])
            elif pending["operation"] == "close" and job is not None:
                member = next((row for row in data["members"] if row["id"] == job["id"]), None)
                if member is None or member["active"] or member["resolution"] is None:
                    tasks[task] = "native_effect_unsettled"
                    continue
            elif pending["operation"] == "measure":
                tasks[task] = "measurement_unsettled"
                continue
        dispatches = {row["id"] for row in state["recovery"]["dispatches"]
                      if row["task"] == task and row["status"] != "not_sent" and row["id"] in identifiers}
        covered.update(row["id"] for row in data["members"]
                       if row["active"] and row["assignment"]["task"] == task and row["id"] in dispatches)
    return {"members": covered, "tasks": tasks}


def coverage(state_path, data, at, plugin_root, *, probe=supervision_runtime.process_identity):
    return continuation(state_path, data, at, plugin_root, probe=probe)["members"]
