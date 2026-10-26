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
from .chronology import timestamp
from .errors import UsageError
from .process_lease import process_lease
from .runnable import command
from .state import save_state


RETRYABLE = frozenset({"release_evidence_unconfirmed", "cleanup_owner_refused",
    "workflow_owner_refused", "evidence_owner_refused", "current_plan_changed",
    "native_owner_refused", "pending_effect_requires_reconciliation"})
READBACK_FIELDS = frozenset({"schema_version", "kind", "sha256"})
READBACK_KINDS = frozenset({"intent_not_started", "snapshot_completed", "probes_closed_incomplete"})


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


def current_measurement_readback(path, data):
    """Derive one request from retained owners, without model-written digests."""
    from .progression_service import capture_contract
    from . import probe_recovery
    from .config import load_config
    fields = {"task", "expected_generation", "intent", "authorization"}
    if not isinstance(data, dict) or set(data) != fields:
        raise UsageError("For --readback-current supply the original task, generation, intent and authorization; omit handwritten readback.", {})
    recovery.text(data["task"], "task")
    recovery.text(data["intent"], "pending intent")
    recovery.authorization(data["authorization"])
    state = authority._load(path)
    grant = authority.current_grant(state, data["task"])
    if (grant is None or grant["mode"] != "service" or grant.get("contract_schema") != 2
            or type(data["expected_generation"]) is not int or data["expected_generation"] != grant["generation"]):
        raise UsageError("Select the current schema-2 task service generation before deriving measurement evidence.", {})
    captured, document = capture_contract(grant["contract"]["path"])
    if captured != grant["contract"]:
        raise UsageError("Restore the admitted contract before deriving its measurement readback.", {})
    progress = state["recovery"]["tasks"][data["task"]]["progression"]
    schema.validate_current(progress, document)
    if progress["pending"] is None:
        matches = [row["details"] for row in state["recovery"]["events"]
                   if row["kind"] == "progression_measurement_reconciled" and row["task"] == data["task"]
                   and all(row["details"].get(key) == value for key, value in data.items())]
        if matches:
            return deepcopy(matches[-1])
        raise UsageError("No matching measurement intent or reconciled owner receipt exists; inspect this task's current exception.", {})
    intent = _measurement_intent(progress, document, data)
    if not intent["effects_started"]:
        readback = {"kind": "intent_not_started", "sha256": supervision.digest(intent)}
    else:
        measured_at = None
        if intent["argv"]:
            if len(intent["argv"]) != 2 or intent["argv"][0] != "--now":
                raise UsageError("Restore this measurement intent's supported owner timestamp; no effect was cleared.", {})
            measured_at = intent["argv"][1]
            timestamp(measured_at, "Measurement intent")
        snapshots = [row for row in state["snapshots"] if measured_at is not None and row.get("measured_at") == measured_at]
        if len(snapshots) > 1:
            raise UsageError("Multiple snapshots match this measurement timestamp; preserve the intent and inspect its actual owner evidence.", {})
        if snapshots:
            readback = {"kind": "snapshot_completed", "sha256": supervision.digest(snapshots[0])}
        else:
            profiles = {item.name: probe_recovery.config_digest(item) for item in load_config(document["config"]["path"])}
            rows = [row for row in probe_recovery.load(path)["records"]
                    if row["config_path"] == document["config"]["path"]
                    and profiles.get(row["worker_kind"]) == row["config_sha256"]
                    and (row["at"] == measured_at if measured_at is not None
                         else timestamp(row["at"], "Probe") >= timestamp(grant["at"], "Task authority"))]
            if not rows or len({row["at"] for row in rows}) != 1:
                raise UsageError("No single measurement attempt has retained canonical probe evidence. Preserve the unknown intent; process absence or timeout supplies no proof.", {})
            readback = {"kind": "probes_closed_incomplete", "sha256": supervision.digest(rows[0])}
    return {**data, "readback": {"schema_version": 1, **readback}}


def _readback(data):
    value = data.get("readback")
    if (not isinstance(value, dict) or set(value) != READBACK_FIELDS
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1 or value.get("kind") not in READBACK_KINDS
            or not isinstance(value.get("sha256"), str)
            or len(value["sha256"]) != 64 or any(char not in "0123456789abcdef" for char in value["sha256"])):
        raise UsageError("Supply one exact canonical measurement/probe readback identity; partial or ambiguous evidence stays pending.", {})
    return value


def _measurement_intent(progress, document, data):
    intent = progress["pending"]
    if (intent is None or intent["id"] != data["intent"] or intent["operation"] != "measure"
            or intent["dispatches"] or intent["job"] is not None
            or intent["inputs"] != [document["config"]]):
        raise UsageError("Reconcile only this task's exact measurement intent and captured configuration; other effects need their own readback.", {})
    return intent


def _canonical_row(rows, digest, label):
    matches = [row for row in rows if supervision.digest(row) == digest]
    if len(matches) != 1:
        raise UsageError("The {} readback is missing or ambiguous in its canonical owner; preserve the pending measurement.".format(label), {})
    return matches[0]


def reconcile_measurement(path, state, grant, supervised, document, data, at, client):
    """Settle one exact measure intent from its state/probe owner, never absence."""
    readback = _readback(data)
    if _replayed(state, data, "progression_measurement_reconciled"):
        return {"task": data["task"], "intent": data["intent"], "outcome": readback["kind"],
                "replayed": True, "authorizes_dispatch": False}
    progress = state["recovery"]["tasks"][data["task"]]["progression"]
    schema.validate_current(progress, document)
    intent = _measurement_intent(progress, document, data)
    workspace.inputs(document)

    if readback["kind"] == "intent_not_started":
        if intent["effects_started"] or supervision.digest(intent) != readback["sha256"]:
            raise UsageError("Only the canonical intent's durable effects_started=false state proves a pre-effect measurement refusal.", {})
    else:
        if not intent["effects_started"]:
            raise UsageError("A started-effect readback cannot replace the canonical pre-effect intent state.", {})
        from . import measurement_retry, probe_recovery
        from .config import load_config
        templates = load_config(document["config"]["path"])
        probe_rows = probe_recovery.load(path)["records"]
        if readback["kind"] == "snapshot_completed":
            if len(intent["argv"]) != 2 or intent["argv"][0] != "--now":
                raise UsageError("A legacy measurement without its durable owner timestamp cannot adopt a later snapshot; use its actual probe readback or preserve it unknown.", {})
            measured_at = intent["argv"][1]
            timestamp(measured_at, "Measurement intent")
            snapshot = _canonical_row(state["snapshots"], readback["sha256"], "measurement snapshot")
            expected_context = measurement_retry.context_digest(templates, client)
            if (snapshot.get("measured_at") != measured_at or expected_context is None
                    or snapshot.get("measurement_context_sha256") != expected_context
                    or set(snapshot.get("agents", {})) != {template.name for template in templates}):
                raise UsageError("The completed snapshot does not bind this intent's timestamp, exact configuration and native measurement context. Restore the captured configuration/native context and rerun `{}` with the same recovery record; preserve the pending intent if that evidence cannot be restored.".format(command("progression-reconcile --readback-current")), {})
            if any(row["status"] == "pending" and row["at"] == measured_at for row in probe_rows):
                raise UsageError("The snapshot retains an unresolved probe owner; close that exact probe before settling measurement.", {})
        else:
            row = _canonical_row(probe_rows, readback["sha256"], "probe")
            template = next((item for item in templates if item.name == row["worker_kind"]), None)
            if (row["status"] != "closed" or row["phase"] not in {"startup", "cleanup"}
                    or template is None or row["config_path"] != document["config"]["path"]
                    or row["config_sha256"] != probe_recovery.config_digest(template)):
                raise UsageError("The probe readback is partial or belongs to different measurement inputs; preserve the pending intent.", {})
            if intent["argv"]:
                if len(intent["argv"]) != 2 or intent["argv"] != ["--now", row["at"]]:
                    raise UsageError("The closed probe does not bind this measurement intent's exact owner timestamp.", {})
            else:
                if timestamp(row["at"], "Probe") < timestamp(grant["at"], "Task authority"):
                    raise UsageError("A probe from before task admission cannot settle this legacy measurement intent.", {})
                same_inputs = [item for item in probe_rows if item["config_path"] == row["config_path"]
                               and item["config_sha256"] == row["config_sha256"]
                               and timestamp(item["at"], "Probe") >= timestamp(grant["at"], "Task authority")]
                if len(same_inputs) != 1:
                    raise UsageError("Legacy probe evidence is ambiguous across measurement attempts; preserve the original intent.", {})
            if any(item["status"] == "pending" for item in probe_rows):
                raise UsageError("At least one retained probe outcome is still partial; resolve its actual owner before reconciliation.", {})
        agents = client.agent_list()
        if (not isinstance(agents, list)
                or any(not isinstance(item, dict) or not isinstance(item.get("name"), str)
                       or not item["name"].strip() or item["name"].startswith("probe-") for item in agents)
                or len({item["name"] for item in agents}) != len(agents)):
            raise UsageError("A disposable probe is still live or native inventory is ambiguous; preserve it for its measurement owner. Inspect native inventory and finish the actual probe cleanup/recovery before rerunning `{}` with the same record. The pending intent is preserved.".format(command("progression-reconcile --readback-current")), {})

    def change(current):
        authority._settled(state, current, data["task"])
        progress.update(pending=None, at=at)
        schema.validate_current(progress, document)
    result = _commit(path, state, grant, supervised, data, at, "progression_measurement_reconciled", change)
    return {**result, "intent": data["intent"], "outcome": readback["kind"]}


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
    if _replayed(state, data, "progression_exception_resumed"):
        return {"task": data["task"], "replayed": True, "authorizes_dispatch": False}
    if progress["phase"] != "exception":
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
