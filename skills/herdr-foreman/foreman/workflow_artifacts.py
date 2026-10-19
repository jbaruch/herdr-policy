"""Retire only a settled native task's private working files.

The existing cleanup intent holds each bounded batch's byte receipts. No
archive or additional ledger is created. Unknown entries, active deliveries,
links and changed evidence remain for their owner instead of being removed.
"""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat

from . import recovery, supervision, workflow_workspace as workspace
from .errors import StateError, UsageError


MAX_FILES = 256
BATCH_FILES = 32


@contextmanager
def _directory(root):
    root = Path(root)
    if root.resolve() != root:
        raise UsageError("Preserve the aliased artifact directory and restore its admitted private path before cleanup.", {})
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        yield None
        return
    except OSError:
        raise StateError("Cannot open the task's private artifact directory; preserve it and restore owner visibility.", {}) from None
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise UsageError("Preserve shared or foreign artifact directories; cleanup requires the original private owner directory.", {})
        yield descriptor
    finally:
        os.close(descriptor)


def _names(descriptor):
    names = []
    with os.scandir(descriptor) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > MAX_FILES:
                raise UsageError("The task directory exceeds the cleanup inventory budget; preserve it for a bounded owner reconciliation.", {})
    return names


def _capture(descriptor, name, root):
    try:
        file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(file, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid():
                raise UsageError("Preserve linked, shared or non-file task artifacts instead of retiring another owner's bytes.", {})
            body = stream.read(workspace.INPUT_LIMIT + 1)
            after = os.fstat(stream.fileno())
        if (len(body) > workspace.INPUT_LIMIT
                or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_nlink)
                != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_nlink)):
            raise UsageError("A task artifact changed or exceeded its input budget; preserve the directory before cleanup.", {})
    except OSError:
        raise StateError("Cannot inventory this task's regular artifact bytes; preserve the original files and restore access.", {}) from None
    return {"path": str(root / name), "sha256": hashlib.sha256(body).hexdigest()}, body, before


def inventory(service, state, progress):
    """Return owned remaining receipts, or None when the directory is absent."""
    root = Path(service.document["artifact_directory"])
    task = service.capability.task
    members = supervision.load(service.path)["members"]
    known, reports, briefs = {"common.md", "plan.json"}, {}, []
    for member in members:
        assigned = supervision.expected_assignment(member)
        if Path(assigned["report"]).parent == root and (
                assigned["task"] != task or member["active"] or member["resolution"] is None):
            raise UsageError("Preserve a directory with another task or an unresolved native enrollment; close its actual obligation first.", {})
    for row in state["recovery"]["dispatches"]:
        if Path(row["brief"]).parent != root and Path(row["common"]).parent != root:
            continue
        if (row["task"] != task or row["status"] != "applied"
                or re.fullmatch(r"workflow-[a-f0-9]{48}:(developer|reviewer|tester|release)", row["id"]) is None
                or Path(row["brief"]).parent != root or Path(row["common"]) != root / "common.md"):
            raise UsageError("Preserve artifacts shared with another task or an unsettled dispatch; reconcile its actual owner first.", {})
        member = next((item for item in members if item["id"] == row["id"]), None)
        if member is None or member["active"] or member["resolution"] is None:
            raise UsageError("Retain every native report until its actual enrollment and delivery obligations are closed.", {})
        expected = supervision.expected_assignment(member)
        report = Path(expected["report"])
        if expected["task"] != task or report.parent != root:
            raise UsageError("Preserve the mismatched task report; a directory name does not establish ownership.", {})
        receipts = [item for item in member["resolution"]["evidence"] if item["path"] == str(report)]
        if len(receipts) != 1:
            raise UsageError("Retain the native report until one byte-bound closure receipt identifies it.", {})
        reports[report.name] = receipts[0]
        briefs.append((row, str(report)))
        identifier = row["id"].replace(":", "-")
        known.update({Path(row["brief"]).name, report.name, "delivery-{}.json".format(identifier)})
        if row["role"] == "release":
            known.add("reviews-{}.json".format(identifier))
    with _directory(root) as descriptor:
        if descriptor is None:
            return None
        names = _names(descriptor)
        if any(name not in known for name in names):
            raise UsageError("Unowned files remain in the task directory; preserve them and reconcile their purpose before cleanup.", {})
        captured = {name: _capture(descriptor, name, root) for name in names}
        for name, expected in reports.items():
            if name in captured and captured[name][0] != {key: expected[key] for key in ("path", "sha256")}:
                raise UsageError("A closed native report changed; preserve its bytes and original closure evidence.", {})
        contents = {item[0]["path"]: item[1] for item in captured.values()}
        for row, report in briefs:
            if row["brief"] not in contents:
                continue
            if row["common"] not in contents or recovery.brief_identity(
                    {"common": row["common"], row["role"]: row["brief"]}, row["role"], report, contents) != row["brief_identity"]:
                raise UsageError("A dispatched brief changed; preserve its original task evidence instead of retiring substituted bytes.", {})
        if "plan.json" in captured:
            identifier = "workflow-" + supervision.digest([task, progress["generation"], progress["round"],
                "release", captured["plan.json"][0]["sha256"]])[:48] + ":release"
            if progress["jobs"].get("release") != identifier:
                raise UsageError("The current plan differs from the final release reservation; preserve it for reconciliation.", {})
        # Keep common bytes available while any remaining brief needs checking.
        return [captured[name][0] for name in sorted(names, key=lambda name: (name in {"common.md", "plan.json"}, name))]


def remove_batch(root, expected, *, allow_missing):
    """Preflight the complete batch before unlinking; a started batch can resume."""
    try:
        return _remove_batch(root, expected, allow_missing=allow_missing)
    except OSError:
        raise StateError("Artifact cleanup was interrupted; preserve its started intent and reconcile the remaining regular files before continuing.", {}) from None


def _remove_batch(root, expected, *, allow_missing):
    root = Path(root)
    with _directory(root) as descriptor:
        if descriptor is None:
            return
        current = set(_names(descriptor))
        pending = []
        for receipt in expected:
            path = Path(receipt["path"])
            if path.parent != root or path.name in {"", ".", ".."}:
                raise UsageError("Retire only receipt-bound files directly inside this task's admitted artifact directory.", {})
            if path.name not in current and allow_missing:
                continue
            captured, _body, info = _capture(descriptor, path.name, root)
            if captured != receipt:
                raise UsageError("A pending cleanup artifact changed; preserve all remaining files and reconcile the original intent.", {})
            pending.append((path.name, info))
        for name, expected_info in pending:
            actual = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (actual.st_dev, actual.st_ino, actual.st_size, actual.st_mtime_ns, actual.st_nlink) != (
                    expected_info.st_dev, expected_info.st_ino, expected_info.st_size,
                    expected_info.st_mtime_ns, expected_info.st_nlink):
                raise UsageError("A cleanup target changed after inventory; preserve the remaining task directory.", {})
            _same_directory(root, descriptor)
            os.unlink(name, dir_fd=descriptor)
        if not _names(descriptor):
            _same_directory(root, descriptor)
            os.rmdir(root)


def _same_directory(root, descriptor):
    held, current = os.fstat(descriptor), root.lstat()
    if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
        raise UsageError("The task artifact directory was replaced; preserve both directories for their actual owners.", {})
