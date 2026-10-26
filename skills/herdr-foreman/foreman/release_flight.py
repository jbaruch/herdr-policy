"""Reader-only task fence for a Git-owned release checkout transaction.

Schema 1 locator: <canonical-state>.release-<sha256(task)>.json, private and
at most 4 KiB, fields LOCATOR_FIELDS below. It references one immutable bounded
Git intent by exact path/SHA and its deterministic schema-1 ready receipt.
The Git intent owns checkout provenance; this locator is no second task store.
Ready proves only absence of this in-flight fence, never dispatch/rebind or
release authority. Other live Git, report, source, role and hold checks remain.

No writer, migration, scan, cleanup or caller bypass exists in these readers.
First checkout writes follow the shared release activation: 0.19.0 keeps it
disabled until both package channels publish these readers. Only that owner
retires its settled locator.
Unknown/changed/foreign/unreadable records hold the selected task and preserve
all bytes. Missing locator means no checkout fence, not accepted task evidence.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import NoReturn

from .errors import StateError, UsageError

LOCATOR_VERSION = 1
LOCATOR_BYTES, INTENT_BYTES = 4_096, 65_536
LOCATOR_FIELDS = {"schema_version", "state_path", "task", "intent", "ready", "generation", "task_sha256"}
READY_FIELDS = {"schema_version", "state_path", "task", "intent", "generation", "task_sha256", "authorizes_progression"}
INTENT_FIELDS = {"schema_version", "state_path", "task", "source", "path", "branch", "head", "base_revision",
                 "source_provenance", "evidence", "binding", "at", "authorizes_release"}
SHA = re.compile(r"[a-f0-9]{64}\Z")
TASK_FACTS = ("task", "base_revision", "scope", "allowed_paths", "authorization", "at")


def locator_path(state_path, task):
    return Path(str(Path(state_path).resolve()) + ".release-" + hashlib.sha256(task.encode()).hexdigest() + ".json")


def task_fingerprint(task_row, binding):
    """Immutable registered scope plus original intent owner; no progress facts."""
    value = {"task": {key: task_row[key] for key in TASK_FACTS}, "binding": binding}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fail(task, reason, message, *, unreadable=False) -> NoReturn:
    kind = StateError if unreadable else UsageError
    raise kind(message + " Preserve the locator and original Git intent. Resume that exact checkout transaction through its owner; do not delete a fence or assume no Git effect.",
               {"reason": reason, "task": task, "authorizes_progression": False})


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _read(path, task, limit, *, absent=False):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > limit):
            _fail(task, "release_checkout_evidence_unsafe", "Use this owner's original bounded private regular checkout metadata.")
        body = os.read(descriptor, limit + 1)
        current = path.lstat()
        if len(body) > limit or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            _fail(task, "release_checkout_evidence_changed", "Checkout metadata changed during its bounded read.")
        return json.loads(body, object_pairs_hook=_unique), body
    except FileNotFoundError:
        if absent and not path.is_symlink():
            return None
        _fail(task, "release_checkout_evidence_unreadable", "Restore the missing original checkout metadata.", unreadable=True)
    except (OSError, ValueError):
        _fail(task, "release_checkout_evidence_unreadable", "Restore this owner's readable supported checkout metadata; linked or malformed evidence cannot clear a task.", unreadable=True)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _object(value, fields, task):
    if (not isinstance(value, dict) or set(value) != fields
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1):
        _fail(task, "release_checkout_schema_unsupported", "Update the matching checkout owner for this complete metadata schema; an unknown version is not an empty fence.")


def _receipt(value, task):
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value["path"], str) or not Path(value["path"]).is_absolute()
            or Path(value["path"]).resolve() != Path(value["path"])
            or not isinstance(value["sha256"], str) or SHA.fullmatch(value["sha256"]) is None):
        _fail(task, "release_checkout_reference_invalid", "Restore the exact absolute immutable Git-intent receipt.")


def _intent(locator, task):
    path = Path(locator["intent"]["path"])
    parsed = _read(path, task, INTENT_BYTES)
    if parsed is None:
        _fail(task, "release_checkout_evidence_unreadable", "Restore the original Git intent.", unreadable=True)
    value, body = parsed
    _object(value, INTENT_FIELDS, task)
    if (hashlib.sha256(body).hexdigest() != locator["intent"]["sha256"]
            or value["state_path"] != locator["state_path"] or value["task"] != task
            or value["authorizes_release"] is not False
            or not isinstance(value["path"], str) or not Path(value["path"]).is_absolute()
            or not isinstance(value["source"], str) or not Path(value["source"]).is_absolute()
            or value["source"] == value["path"]
            or path.name != "foreman-release-" + hashlib.sha256(value["path"].encode()).hexdigest() + ".json"
            or locator["ready"] != str(path) + ".ready"):
        _fail(task, "release_checkout_reference_changed", "The selected checkout locator and original immutable Git intent do not agree.")
    from . import progression_owner as authority, provision, recovery, supervision, workflow_contract
    try:
        original = provision.validate(value["source_provenance"])
        recovery.revision(value["head"], "release checkout head")
        recovery.revision(value["base_revision"], "release checkout base")
        supervision.timestamp(value["at"])
        binding = value["binding"]
        if (original["path"] != value["source"] or original["branch"] != value["branch"]
                or original["base_revision"] != value["base_revision"]
                or not isinstance(binding, dict) or set(binding) != {"generation", "digest"}
                or type(binding["generation"]) is not int or binding["generation"] < 1
                or not isinstance(binding["digest"], str) or SHA.fullmatch(binding["digest"]) is None):
            raise ValueError()
        evidence = value["evidence"]
        if not isinstance(evidence, dict):
            raise ValueError()
        if evidence.get("kind") == "ledger":
            captured = evidence.get("receipt")
            if (set(evidence) != {"kind", "receipt"} or not isinstance(captured, dict)
                    or set(captured) != {"path", "sha256", "bytes"} or type(captured["bytes"]) is not int
                    or not 0 < captured["bytes"] <= 2_097_152):
                raise ValueError()
            _receipt({key: captured[key] for key in ("path", "sha256")}, task)
        elif evidence.get("kind") == "workflow":
            if set(evidence) != {"kind", "grant", "progress", "reports", "successor"}:
                raise ValueError()
            authority.validate_grant(evidence["grant"])
            workflow_contract.validate_progress(evidence["progress"])
            if (evidence["grant"]["mode"] != "service" or evidence["grant"].get("contract_schema") not in (2, 3)
                    or evidence["grant"]["generation"] != locator["generation"]
                    or evidence["grant"]["binding"] != value["binding"]
                    or not isinstance(evidence["reports"], list) or not 2 <= len(evidence["reports"]) <= 3):
                raise ValueError()
            for captured in [*evidence["reports"], evidence["successor"]]:
                _receipt(captured, task)
        else:
            raise ValueError()
    except (UsageError, ValueError, KeyError, TypeError):
        _fail(task, "release_checkout_intent_unsupported", "Restore the supported complete original checkout intent and its base/evidence types.")
    return value


def inspect(state_path, state, task):
    """Return bounded fence facts for one selected task, with no Git/native I/O."""
    location = locator_path(state_path, task)
    parsed = _read(location, task, LOCATOR_BYTES, absent=True)
    if parsed is None:
        return None
    locator, _body = parsed
    _object(locator, LOCATOR_FIELDS, task)
    if (locator["state_path"] != str(Path(state_path).resolve()) or locator["task"] != task
            or type(locator["generation"]) is not int or locator["generation"] < 0
            or not isinstance(locator["task_sha256"], str) or SHA.fullmatch(locator["task_sha256"]) is None
            or not isinstance(locator["ready"], str) or not Path(locator["ready"]).is_absolute()):
        _fail(task, "release_checkout_locator_unbound", "The checkout locator does not bind this exact task, owner and original generation.")
    _receipt(locator["intent"], task)
    intent = _intent(locator, task)
    task_row = state["recovery"]["tasks"].get(task)
    if task_row is None or task_row["base_revision"] != intent["base_revision"]:
        _fail(task, "release_checkout_locator_unbound", "The checkout locator differs from the registered task and original base.")
    if task_fingerprint(task_row, intent["binding"]) != locator["task_sha256"]:
        _fail(task, "release_checkout_task_changed", "The registered task scope/authorization or original intent binding differs from this checkout transaction.")
    parsed = _read(Path(locator["ready"]), task, LOCATOR_BYTES, absent=True)
    completed = parsed is not None
    if completed:
        ready, _body = parsed
        _object(ready, READY_FIELDS, task)
        expected = {key: locator[key] for key in ("state_path", "task", "intent", "task_sha256")}
        expected.update(schema_version=1, generation=locator["generation"], authorizes_progression=False)
        grant = task_row.get("authority")
        if intent["evidence"]["kind"] == "workflow":
            expected["generation"] += 1
            successor = deepcopy(intent["evidence"]["grant"])
            successor.update(generation=expected["generation"], contract=intent["evidence"]["successor"], at=intent["at"])
            if grant != successor or task_row.get("progression", {}).get("generation") != expected["generation"]:
                _fail(task, "release_checkout_ready_unbound", "The ready receipt cannot clear a different current workflow generation or contract.")
        elif (grant is not None and (grant["mode"] != "legacy" or grant["generation"] != expected["generation"])
              or grant is None and expected["generation"] != 0):
            _fail(task, "release_checkout_ready_unbound", "The ready receipt cannot clear a different current legacy task generation.")
        if ready != expected:
            _fail(task, "release_checkout_ready_unbound", "The ready receipt does not match this task, generation and exact original intent.")
    return {"task": task, "pending": not completed, "intent": locator["intent"], "locator": str(location),
            "authorizes_progression": False}


def require_clear(state_path, state, tasks):
    for task in sorted(tasks):
        view = inspect(state_path, state, task)
        if view is not None and view["pending"]:
            _fail(task, "release_checkout_pending", "This task retains an in-flight release checkout handoff. Independent tasks may continue through their own owners.")
