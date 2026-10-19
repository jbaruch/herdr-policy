"""Retire only a settled native task's private working files.

The existing cleanup intent holds each bounded batch's byte receipts. No
archive or additional ledger is created. Unknown entries, active deliveries,
links and changed evidence remain for their owner instead of being removed.
"""

from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat

from . import recovery, report_contract, supervision, workflow_rename, workflow_workspace as workspace
from .errors import StateError, UsageError


MAX_FILES = 256
BATCH_FILES = 32
PHASES = frozenset({"pending", "staging", "retiring", "retired", "legacy_preserved"})


def initial(*, historical=False):
    return {"schema_version": 1, "phase": "legacy_preserved" if historical else "pending",
            "quarantine": None, "root": None, "stage": None, "remaining": []}


def _identity(info):
    return {"schema_version": 1, "device": info.st_dev, "inode": info.st_ino}


def _valid_identity(value):
    return (isinstance(value, dict) and set(value) == {"schema_version", "device", "inode"}
            and type(value["schema_version"]) is int and value["schema_version"] == 1
            and all(type(value[key]) is int and 0 <= value[key] < 1 << 64 for key in ("device", "inode"))
            and value["inode"] > 0)


def _bounded_text(value, limit):
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        return False
    try:
        return len(value.encode()) <= limit
    except UnicodeError:
        return False


def validate(value):
    if (not isinstance(value, dict)
            or set(value) != {"schema_version", "phase", "quarantine", "root", "stage", "remaining"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["phase"], str) or value["phase"] not in PHASES
            or not isinstance(value["remaining"], list)
            or len(value["remaining"]) > MAX_FILES):
        raise UsageError("Restore the supported artifact lifecycle without discarding its remaining cleanup obligations.", {})
    if value["phase"] in {"pending", "retired", "legacy_preserved"}:
        if any(value[key] is not None for key in ("quarantine", "root", "stage")) or value["remaining"]:
            raise UsageError("Preserve unresolved artifact identities; an unfinished quarantine cannot become retired.", {})
        return
    path = value["quarantine"]
    if (not _bounded_text(path, 4096) or not Path(path).is_absolute() or not _valid_identity(value["root"])
            or value["stage"] is not None and not _valid_identity(value["stage"])
            or value["phase"] == "retiring" and value["stage"] is None):
        raise UsageError("Restore this cleanup's private quarantine and original directory identities before resuming it.", {})
    names = set()
    for row in value["remaining"]:
        if (not isinstance(row, dict) or set(row) != {"schema_version", "name", "sha256", "device", "inode"}
                or not _valid_identity({key: row[key] for key in ("schema_version", "device", "inode")})
                or not _bounded_text(row["name"], 128)
                or row["name"] in {".", ".."} or "/" in row["name"] or "\\" in row["name"]
                or row["name"] in names or not isinstance(row["sha256"], str)
                or re.fullmatch(r"[a-f0-9]{64}", row["sha256"]) is None):
            raise UsageError("Preserve the bounded original artifact manifest; unknown, duplicate or changed identities need reconciliation.", {})
        names.add(row["name"])


def view(value):
    return {"schema_version": 1, "kind": "artifact_cleanup_view", "phase": value["phase"],
            "quarantine": value["quarantine"], "finalization_suffix": ".retired",
            "remaining_count": len(value["remaining"])}


def migrate_deliveries(store):
    """Primary owner migration only; never inspect or sweep historical directories."""
    from .workflow_contract import validate_progress
    changed = False
    tasks = store.get("tasks", {})
    if not isinstance(tasks, dict):
        return False
    for task in tasks.values():
        progress = task.get("progression") if isinstance(task, dict) else None
        delivery = progress.get("delivery") if isinstance(progress, dict) else None
        if (isinstance(progress, dict) and progress.get("schema_version") == 2
                and isinstance(delivery, dict) and type(delivery.get("schema_version")) is int
                and delivery["schema_version"] == 1):
            validate_progress(progress)
            delivery.update(schema_version=2, artifacts=initial(historical=progress["phase"] == "complete"))
            changed = True
    return changed


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


def _capture(descriptor, name, root, *, logical_name=None):
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
    return {"path": str(root / (logical_name or name)), "sha256": hashlib.sha256(body).hexdigest()}, body, before


def _proved_unsent(state, row):
    if row["status"] != "not_sent":
        return False
    recorded = (row.get("reconciliation") or {}).get("input", {})
    return (recorded.get("dispatch") == row["id"] and recorded.get("outcome") == "not_sent"
            or any(event["kind"] == "dispatch_not_sent" and event["task"] == row["task"]
                   and event["details"].get("dispatch") == row["id"] for event in state["recovery"]["events"]))


def inventory(service, state, progress):
    """Capture the initial closed-task manifest; never copy a historical archive."""
    root = Path(service.document["artifact_directory"])
    task = service.capability.task
    members = supervision.load(service.path)["members"]
    unsent = {row["id"] for row in state["recovery"]["dispatches"] if _proved_unsent(state, row)}
    known, reports, briefs, reviews = {"common.md", "plan.json"}, {}, [], {}
    for member in members:
        assigned = supervision.expected_assignment(member)
        if Path(assigned["report"]).parent == root and (
                assigned["task"] != task or member["active"]
                or member["resolution"] is None and member["id"] not in unsent):
            raise UsageError("Preserve a directory with another task or an unresolved native enrollment; close its actual obligation first.", {})
    for row in state["recovery"]["dispatches"]:
        if Path(row["brief"]).parent != root and Path(row["common"]).parent != root:
            continue
        if (row["task"] != task or row["status"] != "applied" and row["id"] not in unsent
                or re.fullmatch(r"workflow-[a-f0-9]{48}:(developer|reviewer|tester|release)", row["id"]) is None
                or Path(row["brief"]).parent != root or Path(row["common"]) != root / "common.md"):
            raise UsageError("Preserve artifacts shared with another task or an unsettled dispatch; reconcile its actual owner first.", {})
        member = next((item for item in members if item["id"] == row["id"]), None)
        identifier = row["id"].replace(":", "-")
        if row["id"] in unsent:
            report = Path(supervision.expected_assignment(member)["report"]) if member is not None else root / ("report-" + identifier + ".md")
            if (member is not None and member["active"] or report.parent != root
                    or report.exists() or report.is_symlink()):
                raise UsageError("An owner-proved unsent attempt has a current enrollment or report; preserve its original recovery evidence.", {})
            known.add(Path(row["brief"]).name)
            briefs.append((row, str(report)))
            continue
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
        known.update({Path(row["brief"]).name, report.name, "delivery-{}.json".format(identifier)})
        if row["role"] == "release":
            review = "reviews-{}.json".format(identifier)
            known.add(review)
            reviews[review] = report.name
    with _directory(root) as descriptor:
        if descriptor is None:
            return None
        names = _names(descriptor)
        if any(name not in known for name in names):
            raise UsageError("Unowned files remain in the task directory; preserve them and reconcile their purpose before cleanup.", {})
        captured = {}
        for name in names:
            receipt, body, info = _capture(descriptor, name, root)
            captured[name] = (receipt, body if name == "common.md" or name.startswith("brief-") or name in reports else b"", info)
        for name, expected in reports.items():
            if name in captured and captured[name][0] != {key: expected[key] for key in ("path", "sha256")}:
                raise UsageError("A closed native report changed; preserve its bytes and original closure evidence.", {})
        for name, report in reviews.items():
            if name not in captured:
                continue
            if report not in captured:
                raise UsageError("Retain this review snapshot until its unchanged closed release report supplies its original byte receipt.", {})
            try:
                claim = report_contract.workflow_claim(captured[report][1].decode("utf-8"))
            except UnicodeError:
                raise UsageError("Preserve the unreadable release report and its review snapshot for owner reconciliation.", {}) from None
            expected = claim.get("review_evidence")
            recovery.validate_receipt(expected)
            if captured[name][0] != expected:
                raise UsageError("The release review snapshot differs from its closed report's byte receipt; preserve both artifacts.", {})
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
        return {"root": _identity(os.fstat(descriptor)), "remaining": [
            {**_identity(captured[name][2]), "name": name, "sha256": captured[name][0]["sha256"]}
            for name in sorted(names, key=lambda name: (name in {"common.md", "plan.json"}, name))]}


def prepare(service, state, progress):
    lifecycle = progress["delivery"]["artifacts"]
    if lifecycle["phase"] in {"retired", "legacy_preserved"}:
        return None
    root = Path(service.document["artifact_directory"])
    if lifecycle["phase"] == "pending":
        captured = inventory(service, state, progress)
        if captured is None:
            lifecycle.update(initial(), phase="retired")
            return None
        lifecycle.update(captured, phase="staging",
                         quarantine=str(root.parent / (".herdr-retire-" + secrets.token_hex(16))))
    return [{"path": str(root / row["name"]), "sha256": row["sha256"]}
            for row in lifecycle["remaining"][:BATCH_FILES]]


def _slot(name):
    return "entry-" + hashlib.sha256(name.encode()).hexdigest()[:32]


def _check_directory(descriptor, expected):
    if descriptor is None or _identity(os.fstat(descriptor)) != expected:
        raise UsageError("The cleanup directory identity changed; preserve both the source and quarantine for reconciliation.", {})


def _settled(service, state, lifecycle, *, quarantined):
    task, root = service.capability.task, Path(service.document["artifact_directory"])
    protected = [Path(lifecycle["quarantine"]), _final_path(lifecycle)]
    if not quarantined:
        protected.append(root)
    unsent = {row["id"] for row in state["recovery"]["dispatches"] if _proved_unsent(state, row)}
    for member in supervision.load(service.path)["members"]:
        assigned = supervision.expected_assignment(member)
        unresolved = member["active"] or member["resolution"] is None and member["id"] not in unsent
        if ((assigned["task"] == task and unresolved)
                or any(Path(assigned["report"]).is_relative_to(path) for path in protected) and (
                    assigned["task"] != task or unresolved)):
            raise UsageError("An unresolved or foreign enrollment still needs these working files; preserve the cleanup intent.", {})


def _check_file(descriptor, physical, row, root):
    receipt, _body, info = _capture(descriptor, physical, root, logical_name=row["name"])
    if receipt["sha256"] != row["sha256"] or _identity(info) != {key: row[key] for key in ("schema_version", "device", "inode")}:
        raise UsageError("A cleanup target was replaced or changed; preserve the moved quarantine entry before any deletion.", {})


def _final_path(lifecycle):
    return Path(lifecycle["quarantine"] + ".retired")


def _stage_path(lifecycle):
    final = _final_path(lifecycle)
    if final.exists() or final.is_symlink():
        if lifecycle["remaining"]:
            raise UsageError("An unexpected final quarantine exists before file retirement; preserve both paths.", {})
        return final
    return Path(lifecycle["quarantine"])


def _unrecorded_stage(lifecycle, intent):
    """Read back an interrupted allocation at this intent's exact private path."""
    final = _final_path(lifecycle)
    if final.exists() or final.is_symlink():
        raise UsageError("An unexpected final quarantine exists before allocation settled; preserve both paths.", {})
    with _directory(lifecycle["quarantine"]) as descriptor:
        if descriptor is None:
            return None
        info = os.fstat(descriptor)
        if not intent["effects_started"] or stat.S_IMODE(info.st_mode) != 0o700 or _names(descriptor):
            raise UsageError("Preserve an unrecorded quarantine unless this started intent identifies its exact private, empty directory.", {})
        return _identity(info)


def preflight(service, state, progress):
    """Read original or quarantined targets before recording an effect boundary."""
    lifecycle, intent = progress["delivery"]["artifacts"], progress["pending"]
    root = Path(service.document["artifact_directory"])
    selected = {Path(row["path"]).name for row in intent["inputs"]}
    rows = {row["name"]: row for row in lifecycle["remaining"]}
    with ExitStack() as held:
        if lifecycle["stage"] is None:
            _unrecorded_stage(lifecycle, intent)
            directory = held.enter_context(_directory(root))
            _check_directory(directory, lifecycle["root"])
            stage, names, stage_names, quarantined = None, set(_names(directory)), set(), False
        else:
            stage = held.enter_context(_directory(_stage_path(lifecycle)))
            if stage is None and lifecycle["phase"] == "retiring" and not rows and intent["effects_started"]:
                _settled(service, state, lifecycle, quarantined=True)
                return
            _check_directory(stage, lifecycle["stage"])
            stage_names = set(_names(stage))
            if stage_names - {"task", *(_slot(name) for name in selected)}:
                raise UsageError("Foreign entries exist in the private quarantine; preserve them and the original intent.", {})
            actual, quarantined = Path(lifecycle["quarantine"]) / "task", True
            if "task" not in stage_names and lifecycle["phase"] == "staging":
                actual, quarantined = root, False
            directory = held.enter_context(_directory(actual))
            if directory is not None:
                _check_directory(directory, lifecycle["root"])
            elif rows:
                raise UsageError("The quarantined task directory is missing before its manifest settled; retain the original obligation.", {})
            names = set(_names(directory)) if directory is not None else set()
        _settled(service, state, lifecycle, quarantined=quarantined)
        if names - set(rows):
            raise UsageError("New or unowned files exist in the task directory; preserve them before retirement.", {})
        for name, row in rows.items():
            source = name in names
            staged = stage is not None and _slot(name) in stage_names
            if source and staged:
                raise UsageError("A source reappeared after quarantine; preserve both copies for their actual owners.", {})
            if source:
                _check_file(directory, name, row, root)
            elif staged:
                _check_file(stage, _slot(name), row, root)
            elif not (lifecycle["phase"] == "retiring" and intent["effects_started"] and name in selected):
                raise UsageError("An unprocessed working file is absent; preserve the manifest and reconcile its original bytes.", {})


def resume(service, state, progress, *, checkpoint, before_effect):
    """One owned batch; source names move before their captured inode is trusted."""
    try:
        return _resume(service, state, progress, checkpoint=checkpoint, before_effect=before_effect)
    except OSError:
        raise StateError("Artifact retirement was interrupted; preserve its source and private quarantine and resume the original intent.", {}) from None


def _resume(service, state, progress, *, checkpoint, before_effect):
    lifecycle, intent = progress["delivery"]["artifacts"], progress["pending"]
    root, quarantine = Path(service.document["artifact_directory"]), Path(lifecycle["quarantine"])
    before_effect()
    if lifecycle["stage"] is None:
        allocated = _unrecorded_stage(lifecycle, intent)
        if allocated is None:
            os.mkdir(quarantine, 0o700)
        with _directory(quarantine) as stage:
            if stage is None:
                raise StateError("The newly created quarantine moved before its identity was recorded; preserve both paths and the intent.", {})
            if allocated is not None:
                _check_directory(stage, allocated)
            if _names(stage) or stat.S_IMODE(os.fstat(stage).st_mode) != 0o700:
                raise UsageError("The unrecorded quarantine changed before its checkpoint; preserve its contents and the original intent.", {})
            lifecycle["stage"] = _identity(os.fstat(stage))
            checkpoint()
    with _directory(_stage_path(lifecycle)) as stage:
        if stage is None and lifecycle["phase"] == "retiring" and not lifecycle["remaining"]:
            lifecycle.update(initial(), phase="retired")
            return
        _check_directory(stage, lifecycle["stage"])
        if lifecycle["phase"] == "staging":
            if "task" not in _names(stage):
                workflow_rename.exclusive(root, "task", dst_dir_fd=stage)
            with _directory(quarantine / "task") as directory:
                _check_directory(directory, lifecycle["root"])
            lifecycle["phase"] = "retiring"
            checkpoint()
        preflight(service, state, progress)
        selected = {Path(row["path"]).name for row in intent["inputs"]}
        if selected:
            with _directory(quarantine / "task") as directory:
                _check_directory(directory, lifecycle["root"])
                for row in lifecycle["remaining"]:
                    name = row["name"]
                    if name not in selected:
                        continue
                    slot = _slot(name)
                    if slot not in _names(stage) and name in _names(directory):
                        workflow_rename.exclusive(name, slot, src_dir_fd=directory, dst_dir_fd=stage)
                    if slot in _names(stage):
                        _check_file(stage, slot, row, root)
                        os.unlink(slot, dir_fd=stage)
                    if name in _names(directory):
                        raise UsageError("A task source reappeared during retirement; preserve it and the cleanup manifest.", {})
            lifecycle["remaining"] = [row for row in lifecycle["remaining"] if row["name"] not in selected]
            return
        if "task" in _names(stage):
            with _directory(quarantine / "task") as directory:
                _check_directory(directory, lifecycle["root"])
                if _names(directory):
                    raise UsageError("New task files remain at finalization; preserve them rather than completing cleanup.", {})
            os.rmdir("task", dir_fd=stage)
    final = _final_path(lifecycle)
    if not (final.exists() or final.is_symlink()):
        workflow_rename.exclusive(quarantine, final)
    with _directory(final) as stage:
        _check_directory(stage, lifecycle["stage"])
        if _names(stage):
            raise UsageError("The final quarantine has unrelated contents; preserve it before retiring this task.", {})
        os.rmdir(final)
    lifecycle.update(initial(), phase="retired")
