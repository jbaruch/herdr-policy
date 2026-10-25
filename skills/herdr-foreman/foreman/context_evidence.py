"""Quarantine the known fresh/no-clear writer contradiction (#75).

CLI holds the canonical state lock. Only the existing bound native foreman may
replace the contradictory pair with unknown; no clear/session proof is created.
Original ledger bytes and the original row survive in private immutable files.
The schema-1 journal is an intent: actual current-row readback proves completion.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from . import progression_owner, recovery, supervision
from .errors import StateError, UsageError
from .diagnostics import stderr_warn
from .state import STATE_SCHEMA_VERSION, _NoUsableState, _validate, save_state

SCHEMA_VERSION = 1
FIELDS = frozenset({"schema_version", "id", "assignment_index", "assignment_sha256", "dispatch", "authorization"})
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")


def digest(value):
    """Canonical JSON digest used by the quarantine input contract."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read(path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise StateError("Context recovery requires an owned regular file at {}; preserve links and foreign files.".format(path), {})
        return path.read_bytes()
    except OSError as exc:
        raise StateError("Cannot read context recovery evidence at {}; restore its owned original before retrying: {}.".format(path, exc), {}) from None


def _json(body):
    try:
        value = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise StateError("Context recovery requires intact UTF-8 JSON; restore the original evidence, never an empty owner.", {}) from None
    if not isinstance(value, dict):
        raise StateError("Context recovery requires the original owner object; preserve the current file.", {})
    return value


def _private_directory(root):
    try:
        if not root.exists() and not root.is_symlink():
            return
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise StateError("Quarantine evidence directory must be owned, regular and private; preserve it before retrying.", {})
    except OSError as exc:
        raise StateError("Cannot inspect quarantine evidence directory {}; restore its private directory access and retry without changing the owner: {}.".format(root, exc), {}) from None


def _immutable(path, body):
    """Exclusive private evidence publication; a retained file must match exactly."""
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".context-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read(path) != body:
                raise StateError("Context recovery evidence conflicts at {}; preserve both attempts and use the original identity.".format(path), {}) from None
            if stat.S_IMODE(path.lstat().st_mode) != 0o600:
                raise StateError("Retained context recovery evidence at {} must remain private mode 0600; preserve its contents and restore private access before retrying.".format(path), {})
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise StateError("Cannot preserve context evidence at {}; restore private directory access: {}.".format(path, exc), {}) from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                stderr_warn("Cannot remove private context temporary file {}; restore directory access and remove that temporary file: {}.".format(temporary, exc))


def _validated(candidate, path):
    before = deepcopy(candidate)
    try:
        parsed, migrated = _validate(candidate, path)
    except (_NoUsableState, UsageError):
        raise StateError("Other owner evidence is invalid; preserve the whole ledger and recover that evidence separately.", {}) from None
    if migrated or parsed != before:
        raise StateError("Context quarantine cannot migrate unrelated history; use the compatible owner migration first.", {})
    return parsed


def quarantine(state_path, data, at, client, *, dry_run=False):
    """Revoke only the exact contradictory pair, preserving all other history."""
    if (not isinstance(data, dict) or set(data) != FIELDS or type(data["schema_version"]) is not int
            or data["schema_version"] != SCHEMA_VERSION or not isinstance(data["id"], str)
            or IDENTIFIER.fullmatch(data["id"]) is None or type(data["assignment_index"]) is not int
            or data["assignment_index"] < 0 or not isinstance(data["assignment_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", data["assignment_sha256"]) is None):
        raise UsageError("Supply the version-1 quarantine record, exact row index/digest and a safe unique id; preserve the original owner.", {})
    recovery.authorization(data["authorization"])
    recovery.text(data["dispatch"], "original dispatch")
    supervision.timestamp(at)
    progression_owner.verify_foreman(state_path, client, native_only=True)
    path = Path(state_path).expanduser().absolute()
    body = _read(path)
    state = _json(body)
    rows = state.get("assignments")
    if (state.get("schema_version") != STATE_SCHEMA_VERSION or not isinstance(rows, list)
            or data["assignment_index"] >= len(rows)):
        raise StateError("Restore the matching current owner and original assignment index; context quarantine cannot replace or migrate it.", {})
    row = rows[data["assignment_index"]]
    if not isinstance(row, dict):
        raise StateError("The selected assignment is not the original object; preserve it for its owner.", {})
    root = Path(str(path) + ".context-evidence")
    _private_directory(root)
    journal_path = root / (data["id"] + ".json")
    journal = _json(_read(journal_path)) if journal_path.exists() or journal_path.is_symlink() else None
    if journal is not None:
        if type(journal.get("schema_version")) is not int or journal["schema_version"] != SCHEMA_VERSION:
            raise StateError("Unsupported context quarantine journal version at {}; update the owning herdr-policy installation to support this version, preserving the journal and original owner before retrying.".format(journal_path), {})
        if (journal.get("input") != data or journal.get("state_path") != str(path)
                or not isinstance(journal.get("at"), str)
                or not isinstance(journal.get("original_state_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", journal["original_state_sha256"]) is None):
            raise StateError("Quarantine identity already names different evidence; replay its original input.", {})
        supervision.timestamp(journal["at"])
        original = journal.get("original_assignment")
        if not isinstance(original, dict) or digest(original) != data["assignment_sha256"]:
            raise StateError("The original quarantine row is unreadable; restore its private journal.", {})
    else:
        original = row
    if (digest(original) != data["assignment_sha256"] or original.get("cleared") is not True
            or original.get("clear_reason") != "hand" or original.get("context_session") is not None):
        raise UsageError("Quarantine accepts only the exact true/hand/null-session writer contradiction; other context evidence stays unchanged.", {})
    candidate_row = {**original, "cleared": None, "clear_reason": "unknown"}
    if journal is not None and row == candidate_row:
        _validated(state, path)
        backup = root / (journal["original_state_sha256"] + ".original.json")
        if hashlib.sha256(_read(backup)).hexdigest() != journal["original_state_sha256"]:
            raise StateError("Restore the original ledger backup before acknowledging this quarantine.", {})
        original_state = _json(_read(backup))
        originals = original_state.get("assignments")
        if (not isinstance(originals, list) or data["assignment_index"] >= len(originals)
                or originals[data["assignment_index"]] != original):
            raise StateError("Original quarantine backup does not bind this assignment; restore its actual evidence.", {})
        return {"id": data["id"], "replayed": True, "quarantined": True, "journal": str(journal_path),
                "backup": str(backup), "authorizes_dispatch": False}
    if row != original:
        raise StateError("Assignment changed after quarantine preparation; preserve its actual outcome and the original journal.", {})
    store = state.get("recovery", {})
    dispatches = store.get("dispatches", []) if isinstance(store, dict) else []
    if not isinstance(dispatches, list):
        raise StateError("Restore the original dispatch collection before context quarantine.", {})
    matches = [item for item in dispatches if isinstance(item, dict) and item.get("id") == data["dispatch"]]
    if len(matches) != 1:
        raise StateError("Restore the original unique dispatch before quarantining its context evidence.", {})
    dispatch = matches[0]
    result = dispatch.get("result")
    if (dispatch.get("status") != "applied" or dispatch.get("assignment_index") != data["assignment_index"]
            or any(dispatch.get(key) != original.get(key) for key in ("task", "role", "agent", "fix_round"))
            or not isinstance(result, dict) or result.get("assignment_scoped") is not True
            or result.get("cleared") is not True or result.get("clear_reason") != "hand"
            or result.get("context_session") is not None):
        raise StateError("The dispatch does not prove this recorded writer contradiction; preserve its actual evidence.", {})
    candidate = deepcopy(state)
    candidate["assignments"][data["assignment_index"]] = candidate_row
    _validated(candidate, path)
    state_sha = hashlib.sha256(body).hexdigest()
    if journal is not None and journal.get("original_state_sha256") != state_sha:
        raise StateError("Owner changed after quarantine preparation; inspect its original journal before retrying.", {})
    if dry_run:
        return {"id": data["id"], "dry_run": True, "would_quarantine": True, "authorizes_dispatch": False}
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        _private_directory(root)
        parent = os.open(root.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except OSError as exc:
        raise StateError("Cannot preserve the original ledger in {}; restore private directory access: {}.".format(root, exc), {}) from None
    backup = root / (state_sha + ".original.json")
    _immutable(backup, body)
    if journal is None:
        journal = {"schema_version": SCHEMA_VERSION, "at": at, "input": data, "state_path": str(path),
                   "original_state_sha256": state_sha, "original_assignment": original}
        _immutable(journal_path, (json.dumps(journal, indent=2) + "\n").encode())
    save_state(path, candidate)
    return {"id": data["id"], "replayed": False, "quarantined": True, "journal": str(journal_path),
            "backup": str(backup), "authorizes_dispatch": False}


def prepare(state_path, index, dispatch, identifier, authorization, output, at, client):
    """Derive and validate a private request without exposing ledger history."""
    progression_owner.verify_foreman(state_path, client, native_only=True)
    if type(index) is not int or index < 0:
        raise UsageError("Select the exact nonnegative original assignment index.", {})
    state = _json(_read(Path(state_path).expanduser().absolute()))
    rows = state.get("assignments")
    if not isinstance(rows, list) or index >= len(rows) or not isinstance(rows[index], dict):
        raise StateError("Restore the selected original assignment before preparing its quarantine request.", {})
    data = {"schema_version": SCHEMA_VERSION, "id": identifier, "assignment_index": index,
            "assignment_sha256": digest(rows[index]), "dispatch": dispatch, "authorization": authorization}
    quarantine(state_path, data, at, client, dry_run=True)
    target = Path(output).expanduser().absolute()
    _immutable(target, (json.dumps(data, indent=2) + "\n").encode())
    return {"schema_version": SCHEMA_VERSION, "id": identifier, "request": str(target),
            "assignment_index": index, "assignment_sha256": data["assignment_sha256"],
            "authorizes_dispatch": False}
