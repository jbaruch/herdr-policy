"""Aggregate current-task context allowance across CLI calls (#11).

The foreman owner keeps one capped counter and a fixed creation receipt, never report bodies or
history. All load-set decisions/questions/offsets for unchanged task facts
share an allowance within a foreman-session cap. Changed task facts refresh
only that task's allowance; only a changed supervision-bound foreman identity
refreshes the session cap. This is an exposure gate, never
dispatch, review, acceptance or release authority.
"""

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from .context_output import OUTPUT_BYTES
from .errors import StateError, UsageError
from .state import save_state, state_lock

SCHEMA_VERSION = 1
DECISION_BYTES = 65_536
FOREMAN_BYTES = 262_144
MAX_TASKS = 32
STORE_BYTES = 65_536
PRESENCE_BYTES = 1_024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def location(state_path):
    return Path(str(Path(state_path).expanduser().resolve()) + ".context.json")


def presence_location(state_path):
    return Path(str(Path(state_path).expanduser().resolve()) + ".context-presence.json")


def _foreman(identity):
    if identity is None:
        return _digest(None)
    if isinstance(identity, dict) and identity.get("kind") == "attested-remote":
        from .supervision import normalize_identity
        receipt = normalize_identity(identity, 2)["attestation"]
        if not isinstance(receipt, dict):
            raise StateError("The remote session binding has an unsupported receipt. Restore its owning supervision record before reading more context.", {})
        return _digest({"kind": "attested-remote", "session": {key: receipt[key] for key in (
            "controller_id", "service_principal", "machine_profile_id", "remote_session",
            "workspace_id", "foreman_pane_id", "foreman_terminal_id")}})
    if not isinstance(identity, dict) or not all(isinstance(identity.get(key), str) and identity[key] for key in ("kind", "value")):
        raise StateError("The foreman session binding is unusable. Restore its supervision owner record before reading more context.", {})
    return _digest({key: identity[key] for key in ("kind", "value")})


def generation(state, packet, supervision):
    """Bind selected-task facts, excluding unrelated tasks and query spelling."""
    task = packet["task"]
    return _digest({
        "core": packet["core"],
        "assignments": [row for row in state["assignments"] if row.get("task") == task],
        "recovery": {key: [row for row in value if row.get("task") == task]
                     for key, value in state["recovery"].items() if isinstance(value, list)},
        "assessments": [row for row in state["specialist_assessments"] if row.get("task") == task],
        "members": [{**row, "observed": {key: value for key, value in row["observed"].items() if key != "visible"}}
                    for row in supervision["members"] if row["assignment"].get("task") == task],
        "supervision": {key: value for key, value in (packet["supervision"] or {}).items() if key != "boundary_held"},
    })


def _empty(state_path, foreman):
    return {"schema_version": SCHEMA_VERSION, "state_path": str(state_path),
            "foreman_sha256": foreman, "returned_bytes": 0, "tasks": {}}


def _task(value):
    try:
        return isinstance(value, str) and bool(value) and len(value.encode()) <= 1_024
    except UnicodeEncodeError:
        return False


def _valid(document, state_path):
    if (not isinstance(document, dict)
            or set(document) != {"schema_version", "state_path", "foreman_sha256", "returned_bytes", "tasks"}
            or type(document["schema_version"]) is not int or document["schema_version"] != SCHEMA_VERSION
            or document["state_path"] != str(state_path)
            or not isinstance(document["foreman_sha256"], str) or not SHA256.fullmatch(document["foreman_sha256"])
            or type(document["returned_bytes"]) is not int or not 0 <= document["returned_bytes"] <= FOREMAN_BYTES
            or not isinstance(document["tasks"], dict) or len(document["tasks"]) > MAX_TASKS):
        return False
    for task, row in document["tasks"].items():
        if (not _task(task)
                or not isinstance(row, dict)
                or set(row) != {"schema_version", "state_sha256", "returned_bytes", "responses"}
                or type(row["schema_version"]) is not int or row["schema_version"] != SCHEMA_VERSION
                or not isinstance(row["state_sha256"], str) or not SHA256.fullmatch(row["state_sha256"])
                or type(row["returned_bytes"]) is not int or not 0 < row["returned_bytes"] <= DECISION_BYTES
                or type(row["responses"]) is not int or not 0 < row["responses"] <= row["returned_bytes"]):
            return False
    return sum(row["returned_bytes"] for row in document["tasks"].values()) <= document["returned_bytes"]


def _private_json(path, limit) -> tuple[bool, Any]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False, None
    except OSError:
        raise StateError("Cannot open the context allowance. Preserve its bytes and restore the owner's private regular file before retrying; do not delete or reset counters.", {}) from None
    try:
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > limit):
                raise StateError("The context allowance is not a bounded private owner file. Preserve it and restore the owner's regular mode-0600 file before retrying.", {})
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("oversized allowance")
        return True, json.loads(raw)
    except (OSError, ValueError, RecursionError):
        raise StateError("Cannot read the context allowance. Preserve it and restore valid owner-written state before retrying; do not treat unreadable counters as unused allowance.", {}) from None


def _presence(path, state_path):
    exists, document = _private_json(path, PRESENCE_BYTES)
    if not exists:
        return False
    if (not isinstance(document, dict) or set(document) != {"schema_version", "state_path_sha256"}
            or type(document["schema_version"]) is not int or document["schema_version"] != SCHEMA_VERSION
            or document["state_path_sha256"] != _digest(str(state_path))):
        raise StateError("Context creation receipt is corrupt or unsupported. Preserve both owner files and restore the original receipt before reading more context.", {})
    return True


def _remember(path, state_path):
    """Create one permanent existence receipt after a successful counter commit."""
    raw = (json.dumps({"schema_version": SCHEMA_VERSION, "state_path_sha256": _digest(str(state_path))}) + "\n").encode()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if not _presence(path, state_path):
            raise StateError("The context creation receipt disappeared. Preserve the counter and restore its original receipt before retrying.", {}) from None
        return
    except OSError:
        raise StateError("Cannot create the context receipt. The counter remains charged; restore owner-directory access before retrying.", {}) from None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            if stream.write(raw) != len(raw):
                raise StateError("Context receipt write was incomplete. Preserve both files and restore the owner receipt before retrying.", {})
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise StateError("Cannot commit the context receipt. Preserve the charged counter and restore its owner receipt before retrying.", {}) from None


def _load(path, state_path, foreman, known):
    exists, document = _private_json(path, STORE_BYTES)
    if not exists:
        if known:
            raise StateError("A previously created context counter is missing. Preserve its creation receipt and restore the original charged counter before reading more context; absence does not grant fresh allowance.", {})
        return _empty(state_path, foreman)
    if not _valid(document, state_path):
        raise StateError("Context allowance schema or binding is unsupported. Preserve the file and update or repair its owning Herdr plugin before reading more context.", {})
    if document["foreman_sha256"] == foreman:
        return document
    if foreman == _digest(None):
        raise StateError("A previously bound foreman session is now unavailable. Preserve its counters and restore the supervision binding before reading more context.", {})
    if document["foreman_sha256"] == _digest(None):
        # First binding cannot prove the preceding offline reads belonged to
        # another model context. Carry their charges rather than refund them.
        return {**document, "foreman_sha256": foreman}
    return _empty(state_path, foreman)


def consume(state_path, packet, state_sha256, identity):
    """Debit exact printed JSON bytes durably before returning content.

    CLI holds the primary owner lock while deriving task facts. The separate
    nonblocking counter lock serializes debits. Failed writes return no content;
    a failure after the commit conservatively spends allowance without output.
    """
    selected = Path(state_path).expanduser().resolve()
    path = location(selected)
    foreman = _foreman(identity)
    task = packet["task"]
    if not _task(task) or not isinstance(state_sha256, str) or not SHA256.fullmatch(state_sha256):
        raise UsageError("Select a canonical task with valid current owner facts before reading decision context; taskless enrollments require owner reconciliation.", {})
    with state_lock(path):
        receipt_path = presence_location(selected)
        known = _presence(receipt_path, selected)
        document = _load(path, selected, foreman, known)
        prior = document["tasks"].get(task)
        used, responses = (prior["returned_bytes"], prior["responses"]) if prior and prior["state_sha256"] == state_sha256 else (0, 0)
        if prior is None and len(document["tasks"]) >= MAX_TASKS:
            raise UsageError("This foreman context reached its task counter capacity. Keep unexamined obligations unresolved and use the existing verified foreman reset/resume workflow; do not evict counters or create an archive.",
                             {"reason": "decision_context_capacity", "context_complete": False})
        result = {**packet, "aggregate_budget": {
            "task_state_sha256": state_sha256, "limit_bytes": DECISION_BYTES,
            "previously_returned_bytes": used, "available_bytes_before_response": DECISION_BYTES - used,
            "foreman_limit_bytes": FOREMAN_BYTES, "foreman_previously_returned_bytes": document["returned_bytes"],
            "foreman_available_bytes_before_response": FOREMAN_BYTES - document["returned_bytes"],
        }}
        if result.get("kind") == "evidence_chunk":
            from .load_set import fit_evidence
            result = fit_evidence(result)
        returned = len((json.dumps(result, indent=2) + "\n").encode())
        if returned > OUTPUT_BYTES or used + returned > DECISION_BYTES or document["returned_bytes"] + returned > FOREMAN_BYTES:
            scope = "response" if returned > OUTPUT_BYTES else "task_decision" if used + returned > DECISION_BYTES else "foreman_session"
            raise UsageError("Decision context exhausted a read allowance or exceeds the response budget. Keep unread evidence and gates unresolved; route the specific question to its task owner or use the verified foreman reset/resume workflow. Changing question, decision or offset does not refresh allowance.",
                             {"reason": "decision_context_budget_exceeded", "scope": scope,
                              "previously_returned_bytes": used, "context_complete": False})
        document["tasks"][task] = {"schema_version": SCHEMA_VERSION, "state_sha256": state_sha256,
                                   "returned_bytes": used + returned, "responses": responses + 1}
        document["returned_bytes"] += returned
        if len((json.dumps(document, indent=2) + "\n").encode()) > STORE_BYTES:
            raise UsageError("The context counter document exceeds its storage bound. Keep its counters and unresolved obligations; resume through a fresh verified foreman context instead of deleting state.",
                             {"reason": "decision_context_capacity", "context_complete": False})
        save_state(path, document)
        if not known:
            _remember(receipt_path, selected)
    return result
