"""Derived task holds for attributable contradictory assignment context pairs.

Only a current applied row with one matching applied dispatch and registered
task is isolatable. Every other owner invariant is still validated normally.
The original row is never repaired, downgraded, dropped or accepted here.

Before an owner write, immutable private schema-1 receipts in
<state>.task-evidence/ bind the row/index to an exact original-owner backup.
This module alone owns those evidence files. They grant no authority and are
not an alternate task store. Unknown receipt versions or changed preserved
bytes refuse the write; readers never migrate them. The task hold is derived
again from the original assignment on every read, never from a receipt.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from .diagnostics import stderr_warn
from .errors import StateError, UsageError
from .tiers import canonical_role

SCHEMA_VERSION = 1
MAX_DIAGNOSTICS = 10
MAX_TASK_BYTES = 1_024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def context_fault(state, index):
    """Classify one local fault; missing or ambiguous ownership stays global."""
    from .state import STATE_SCHEMA_VERSION, valid_context_evidence
    rows = state.get("assignments", [])
    if (not isinstance(rows, list) or type(index) is not int or not 0 <= index < len(rows)
            or not isinstance(rows[index], dict)):
        return None
    row = rows[index]
    reason, cleared = row.get("clear_reason"), row.get("cleared")
    if valid_context_evidence(cleared, reason):
        return None
    if (row.get("schema_version") != STATE_SCHEMA_VERSION or row.get("status") != "applied"
            or reason not in ("automatic", "hand", "retained", "reconciled_not_sent", "unknown")
            or cleared is not None and type(cleared) is not bool
            or not isinstance(row.get("task"), str) or not row["task"].strip()):
        return None
    try:
        if len(row["task"].encode("utf-8")) > MAX_TASK_BYTES:
            return None
    except UnicodeError:
        return None
    store = state.get("recovery")
    if not isinstance(store, dict) or not isinstance(store.get("tasks"), dict) or row["task"] not in store["tasks"]:
        return None
    dispatches = store.get("dispatches")
    if not isinstance(dispatches, list):
        return None
    matches = [item for item in dispatches if isinstance(item, dict) and item.get("assignment_index") == index]
    if len(matches) != 1:
        return None
    dispatch = matches[0]
    if (dispatch.get("status") != "applied" or not isinstance(dispatch.get("id"), str)
            or not isinstance(dispatch.get("role"), str)
            or canonical_role(dispatch["role"]) != row.get("role")
            or any(dispatch.get(key) != row.get(key) for key in ("task", "agent", "fix_round"))):
        return None
    return {"schema_version": SCHEMA_VERSION, "assignment_index": index, "assignment_sha256": digest(row), "dispatch": dispatch["id"],
            "task": row["task"], "reason": "contradictory_context_pair", "outcome": "unknown",
            "authorizes_progression": False}


def faults(state):
    if not isinstance(state, dict) or not isinstance(state.get("assignments"), list):
        return []
    return [fault for index in range(len(state["assignments"])) if (fault := context_fault(state, index)) is not None]


def view(state, task=None):
    affected = [row for row in faults(state) if task is None or row["task"] == task]
    return {"held": bool(affected), "affected_rows": affected[:MAX_DIAGNOSTICS], "total": len(affected),
            "omitted": max(0, len(affected) - MAX_DIAGNOSTICS),
            "coverage": "Only attributable context-pair contradictions are isolated; invalid owner authority or unclassifiable evidence still refuses the owner.",
            "recovery": "Keep the original row and dispatch held. Inspect the affected assignment through its owner; the exact #75 quarantine remains separately authorized and narrowly guarded."}


def require_clear(state, tasks):
    held = [row for row in faults(state) if row["task"] in tasks]
    if held:
        raise UsageError("This task has contradictory assignment evidence. Preserve its original row, dispatch and unknown outcome; recover that evidence through its owner before accepting, resending or advancing dependent work.",
                         {"reason": "task_evidence_held", "affected_rows": held[:MAX_DIAGNOSTICS],
                          "affected_count": len(held), "omitted": max(0, len(held) - MAX_DIAGNOSTICS),
                          "authorizes_progression": False})


def _read(path, *, private=False):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or private and stat.S_IMODE(info.st_mode) != 0o600):
                raise StateError("Preserve the original owned regular task evidence at {}; restore its access before writing the owner.".format(path), {})
            return handle.read()
    except OSError:
        raise StateError("Cannot read preserved task evidence at {}; restore the original owned regular file before changing the owner.".format(path), {}) from None


def _publish(path, body):
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".evidence-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read(path, private=True) != body:
                raise StateError("Preserved task evidence conflicts at {}; restore its original bytes before retrying the owner write.".format(path), {}) from None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        raise StateError("Cannot preserve task evidence at {}; restore private directory access and free space before retrying. The original owner is unchanged.".format(path), {}) from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                stderr_warn("Cannot remove private task evidence temporary file {}; restore its directory access and remove this temporary file.".format(temporary))


def preserve(path, state):
    """Retain original bytes before unrelated work rewrites an isolated owner."""
    affected = faults(state)
    if not affected:
        return
    path = Path(path)
    root = Path(str(path) + ".task-evidence")
    try:
        if not root.exists() and not root.is_symlink():
            root.mkdir(mode=0o700)
        info = root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise StateError("Task evidence directory {} must remain owned, regular and private mode 0700; preserve its contents before retrying the owner write.".format(root), {})
    except OSError:
        raise StateError("Cannot preserve original task evidence at {}; restore private parent-directory access before changing the owner.".format(root), {}) from None
    body = None
    for fault in affected:
        key = digest({key: fault[key] for key in ("assignment_index", "assignment_sha256")})
        receipt = root / (key + ".json")
        if receipt.exists() or receipt.is_symlink():
            try:
                record = json.loads(_read(receipt, private=True))
            except ValueError:
                raise StateError("Restore the original task evidence receipt at {}; its unreadable bytes cannot authorize an owner rewrite.".format(receipt), {}) from None
            if (not isinstance(record, dict) or type(record.get("schema_version")) is not int
                    or record["schema_version"] != SCHEMA_VERSION or record.get("fault") != fault
                    or not isinstance(record.get("original_state_sha256"), str)
                    or len(record["original_state_sha256"]) != 64
                    or any(char not in "0123456789abcdef" for char in record["original_state_sha256"])):
                raise StateError("Unsupported or changed task evidence receipt at {}; restore its schema-1 original through its owner before writing.".format(receipt), {})
            backup = root / (record["original_state_sha256"] + ".original.json")
            preserved = _read(backup, private=True)
            if hashlib.sha256(preserved).hexdigest() != record["original_state_sha256"]:
                raise StateError("Restore the original task evidence backup at {}; changed bytes cannot authorize an owner rewrite.".format(backup), {})
            try:
                original = json.loads(preserved)
            except ValueError:
                raise StateError("Restore the original task evidence JSON at {}; unreadable evidence cannot authorize an owner rewrite.".format(backup), {}) from None
            if not isinstance(original, dict) or context_fault(original, fault["assignment_index"]) != fault:
                raise StateError("The original task evidence backup at {} does not bind this assignment; restore its actual preserved owner bytes.".format(backup), {})
            continue
        if body is None:
            body = _read(path)
        try:
            original = json.loads(body)
        except ValueError:
            raise StateError("Preserve the original task owner JSON; unreadable bytes cannot be rewritten as isolated evidence.", {}) from None
        if (not isinstance(original, dict) or context_fault(original, fault["assignment_index"]) != fault):
            raise StateError("The original assignment changed before evidence preservation. Keep the current bytes and retry through its actual owner.", {})
        sha = hashlib.sha256(body).hexdigest()
        _publish(root / (sha + ".original.json"), body)
        _publish(receipt, (json.dumps({"schema_version": SCHEMA_VERSION, "fault": fault,
                                     "original_state_sha256": sha}, indent=2) + "\n").encode())
