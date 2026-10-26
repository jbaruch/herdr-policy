"""Foreman-owned clean same-head release checkout; unknown local files stay put.

The selected task must be settled and the pushed head must remain exact. The
source is detached at that same commit, never reset/cleaned, before its branch
is checked out in a fresh linked worktree. Normal provision schema 1 survives.
This owner alone writes schema-1 foreman-release-checkout.json in private Git;
it binds the task/owner, preserved source and clean successor, not file ownership.
No transcript, source-tree copy or broad preservation ledger is created.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from . import members, progression_owner as authority, provision, recovery, supervision, task_evidence
from . import release_activation, release_flight, release_rebind, workflow_adoption, workflow_workspace as workspace
from .errors import StateError, UsageError
from .process_lease import process_lease
from .state import load_state_checked, state_lock
from .tiers import canonical_role

SCHEMA_VERSION = 1
RECEIPT = "foreman-release-checkout.json"
FIELDS = {"schema_version", "state_path", "task", "source", "path", "branch", "head", "base_revision",
          "source_provenance", "evidence", "binding", "at", "authorizes_release"}
MAX_BYTES = 65_536


def git(path, *arguments):
    return workspace.git(path, *arguments).strip()


def _owned(path, *, directory=False):
    try:
        info = path.lstat()
    except OSError:
        raise StateError("Restore the selected release checkout's original owned paths before retrying; no local files may be discarded.", {}) from None
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.geteuid():
        raise StateError("Keep release checkout metadata in its original owned regular paths; preserve linked or foreign paths.", {})


def _publish(path, value):
    body = (json.dumps(value, indent=2) + "\n").encode()
    if len(body) > MAX_BYTES:
        raise UsageError("Keep the release checkout intent within its private metadata budget; preserve the source instead of copying histories.", {})
    _owned(path.parent, directory=True)
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".release-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            _owned(path)
            if path.stat().st_size > MAX_BYTES or path.read_bytes() != body:
                raise UsageError("The release checkout receipt already names different evidence; preserve it and retry only its original task/head.", {}) from None
    except OSError:
        raise StateError("Cannot preserve private release-checkout metadata; restore Git-directory access and free space, retaining both checkouts.", {}) from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except OSError as exc:
                if not isinstance(exc, FileNotFoundError):
                    from .diagnostics import stderr_warn
                    stderr_warn("Cannot remove the private release metadata temporary file {}; preserve it and restore Git-directory access.".format(temporary))


def receipt_path(path):
    return Path(git(path, "rev-parse", "--path-format=absolute", "--git-path", RECEIPT))


def _paths(source, target):
    source, target = Path(source), Path(target)
    root = Path(os.environ.get("WORKTREE_ROOT", str(Path.home() / ".worktrees"))).resolve()
    if (not source.is_absolute() or not target.is_absolute() or source.resolve() != source
            or target.parent.resolve() != target.parent or target == source or target.parent != root
            or source.parent != root
            or any(ord(character) < 32 for character in str(source) + str(target))):
        raise UsageError("Select distinct absolute source/release paths directly under the configured worktree root, without aliases; preserve existing files.", {})
    _owned(source, directory=True)
    return source, target


def _pushed_head(source, branch, expected):
    fetch = git(source, "remote", "get-url", "origin")
    pushes = git(source, "remote", "get-url", "--push", "--all", "origin").splitlines()
    if not pushes or any(value != fetch for value in pushes):
        raise UsageError("Restore the task's matching fetch/push origin before preparing release; conflicting targets remain unchanged.", {})
    git(source, "fetch", "--quiet", "origin")
    remote = git(source, "ls-remote", "--heads", "origin", "refs/heads/" + branch).splitlines()
    if (len(remote) != 1 or remote[0].split("\t") != [expected, "refs/heads/" + branch]
            or git(source, "rev-parse", "HEAD") != expected
            or git(source, "rev-parse", "refs/heads/" + branch) != expected
            or git(source, "rev-parse", "refs/remotes/origin/" + branch) != expected):
        raise UsageError("The source, local branch and freshly fetched remote must all equal the independently verified head; preserve changed refs and obtain current verification.", {})


def _ready_ledger(path, state_path, task, base, head):
    if path is None:
        raise UsageError("Supply this legacy task's owner-bound ledger with the exact same-head ready_for_release event.", {})
    workspace.capture(path, limit=workspace.INPUT_LIMIT)
    header, events = members.ledger_events(path)
    if (header["task"] != task or header["base_revision"] != base
            or members._resolve_bound(path, header["dispatch_state"]) != str(Path(state_path).resolve())):
        raise UsageError("Use this task's original owner-bound ledger and base before release checkout preparation.", {})
    latest = next((row for row in reversed(events) if row["subject"] == "task"), None)
    if latest is None or latest["decision"] != "ready_for_release" or latest["head_revision"] != head:
        raise UsageError("Record the actual same-head independent verification in the task's ready_for_release ledger event before preparing its release checkout.", {})
    evidence = supervision.receipt(str(Path(path).resolve()))
    return {"path": evidence["path"], "sha256": evidence["sha256"], "bytes": evidence["size"]}


def _writer_path(dispatch, *, branch=None):
    """Only supported owner-composed brief fields establish a writer scope."""
    _captured, raw = workspace.capture(dispatch["brief"])
    body = raw.decode()
    marker = "## Admitted current task\n\n```json\n"
    if body.count(marker) == 1:
        try:
            context = json.loads(body.split(marker, 1)[1].split("\n```", 1)[0])
        except ValueError:
            raise UsageError("Restore the pending writer's original owner-composed task context before moving a checkout.", {}) from None
        if isinstance(context, dict) and context.get("task") == dispatch["task"] and isinstance(context.get("repository"), dict):
            value = context["repository"].get("worktree")
            if isinstance(value, str) and Path(value).is_absolute() and (branch is None or context["repository"].get("branch") == branch):
                return str(Path(value).resolve())
    matches = re.findall(r"Your worktree (?:already exists at|is) `([^`\n]+)`, on branch `([^`\n]+)`,", body)
    if len(matches) == 1 and Path(matches[0][0]).is_absolute() and (branch is None or matches[0][1] == branch):
        return str(Path(matches[0][0]).resolve())
    raise UsageError("A current writer's checkout scope is unknown. Restore its recorded brief/contract before moving the selected source; an idle process is not proof of task authority.",
                     {"reason": "release_checkout_writer_scope_unknown"})


def _writers_clear(state, supervised, task, source):
    active = {row["id"] for row in supervised["members"] if row["active"]}
    if active - {row["id"] for row in state["recovery"]["dispatches"]}:
        raise UsageError("An active enrollment lacks its original dispatch scope. Reconcile that unknown writer through its owner before moving a branch.",
                         {"reason": "release_checkout_writer_scope_unknown"})
    for dispatch in state["recovery"]["dispatches"]:
        if dispatch["task"] == task or canonical_role(dispatch["role"]) not in ("developer", "release"):
            continue
        if dispatch["status"] in recovery.PENDING_STATUSES or dispatch["id"] in active:
            grant = authority.current_grant(state, dispatch["task"])
            if grant is not None and grant["mode"] == "service" and grant.get("contract_schema") in (2, 3):
                from .progression_service import capture_contract
                from .workflow_contract import contract
                _owned(Path(grant["contract"]["path"]))
                captured, document = capture_contract(grant["contract"]["path"])
                contract(document, state["recovery"]["tasks"][dispatch["task"]])
                if captured != grant["contract"]:
                    raise UsageError("Restore the other current writer's immutable contract before moving a potentially shared source.", {})
                selected = str(Path(document["repository"]["worktree"]).resolve())
            else:
                member = next((row for row in supervised["members"] if row["id"] == dispatch["id"]), None)
                if member is None:
                    raise UsageError("A pending writer has no byte-bound enrollment scope yet. Preserve that unknown send and reconcile its original owner before moving this branch.",
                                     {"reason": "release_checkout_writer_scope_unknown"})
                _owned(Path(dispatch["brief"]))
                _owned(Path(dispatch["common"]))
                workflow_adoption.brief_evidence(dispatch, supervision.expected_assignment(member))
                selected = _writer_path(dispatch)
            if selected == str(source):
                raise UsageError("Another task still owns a writer/release effect in this checkout. Preserve its active/pending obligation before moving the branch.",
                                 {"reason": "release_checkout_other_writer"})


def _prefix(expected):
    _owned(Path(expected["path"]))
    try:
        with Path(expected["path"]).open("rb") as stream:
            body = stream.read(expected["bytes"])
    except OSError:
        raise StateError("Restore the original release ledger prefix before retrying this handoff.", {}) from None
    if len(body) != expected["bytes"] or hashlib.sha256(body).hexdigest() != expected["sha256"]:
        raise UsageError("The recorded ready-for-release ledger prefix changed; preserve its history and reconcile the original evidence before retrying.", {})


def _read(location):
    _owned(location)
    try:
        if location.stat().st_size > MAX_BYTES:
            raise ValueError()
        value = json.loads(location.read_text())
    except (OSError, ValueError):
        raise StateError("Restore this release checkout's original bounded private Git intent/receipt before dispatch.", {}) from None
    if (not isinstance(value, dict) or set(value) != FIELDS
            or type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION
            or value["authorizes_release"] is not False or not isinstance(value["evidence"], dict)
            or value["evidence"].get("kind") not in ("ledger", "workflow")):
        raise UsageError("Restore the supported complete private release checkout receipt; unknown/foreign metadata confers no authority.", {})
    provision.validate(value["source_provenance"])
    for key in ("state_path", "source", "path"):
        if not isinstance(value[key], str) or not Path(value[key]).is_absolute():
            raise UsageError("Restore the original absolute paths in the private release checkout receipt.", {})
    recovery.text(value["task"], "release checkout task")
    recovery.revision(value["head"], "release checkout head")
    recovery.revision(value["base_revision"], "release checkout base")
    supervision.timestamp(value["at"])
    evidence = value["evidence"]
    if evidence["kind"] == "ledger":
        if (set(evidence) != {"kind", "receipt"} or not isinstance(evidence["receipt"], dict)
                or set(evidence["receipt"]) != {"path", "sha256", "bytes"}
                or type(evidence["receipt"]["bytes"]) is not int or not 0 < evidence["receipt"]["bytes"] <= workspace.INPUT_LIMIT):
            raise UsageError("Restore the original bounded ready-for-release ledger receipt.", {})
        recovery.validate_receipt({key: evidence["receipt"][key] for key in ("path", "sha256")})
    else:
        from . import workflow_contract
        if (set(evidence) != {"kind", "grant", "progress", "reports", "successor"}
                or not isinstance(evidence["reports"], list) or not 2 <= len(evidence["reports"]) <= 3):
            raise UsageError("Restore the complete original settled workflow handoff evidence; missing coverage supplies no authority.", {})
        authority.validate_grant(evidence["grant"])
        if evidence["grant"]["mode"] != "service" or evidence["grant"].get("contract_schema") not in (2, 3):
            raise UsageError("Restore the original admitted workflow grant in this checkout handoff; a returned/prepared grant supplies no release-path authority.", {})
        workflow_contract.validate_progress(evidence["progress"])
        for captured in [*evidence["reports"], evidence["successor"]]:
            recovery.validate_receipt(captured)
    return value


def prepare(state_path, task, source, target, head, ledger, at, client, plugin_root):
    """Own short commit locks; native/Git inspection holds neither owner lock."""
    recovery.text(task, "task")
    recovery.revision(head, "verified release head")
    supervision.timestamp(at)
    state, usable = load_state_checked(state_path, persist_migration=False)
    if not usable:
        raise StateError("Restore the original readable task owner before preparing a release checkout; never replace it with an empty ledger.", {})
    registered = recovery.task_record(state["recovery"], task)
    task_evidence.require_clear(state, {task})
    if recovery.task_closure(state["recovery"], state["assignments"], task) is not None:
        raise UsageError("This task is already closed. Preserve its delivered history; a release checkout cannot reopen authority.", {})
    supervised = authority.verify_foreman(state_path, client, native_only=True)
    authority._settled(state, supervised, task)
    if authority._unresumed_hold(supervised):
        raise UsageError("Preserve the global operator hold and its resume condition before release checkout preparation.", {})
    grant = authority.current_grant(state, task)
    if grant is not None and grant["mode"] == "service":
        # Refuse an already running owner before producing any intent. The
        # mutation below claims the lease again for its entire Git handoff.
        with process_lease(grant["lease_path"]):
            pass
    source, target = _paths(source, target)
    _writers_clear(state, supervised, task, source)
    original_path = provision.receipt_path(source)
    _owned(original_path)
    try:
        if original_path.stat().st_size > MAX_BYTES:
            raise ValueError()
        original = provision.validate(json.loads(original_path.read_text()))
    except (OSError, ValueError):
        raise StateError("Restore the original readable provisioning receipt; unknown local files remain preserved.", {}) from None
    branch = original["branch"]
    if original["fetched_default_ref"] == "origin/" + branch:
        raise UsageError("Prepare release from the isolated feature branch, preserving the repository's default branch and shared checkout.", {})
    if original["path"] != str(source) or original["base_revision"] != registered["base_revision"]:
        raise UsageError("The source provisioning receipt must retain this exact task path and original base; preserve all existing provenance.", {})
    common = git(source, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if (git(source, "rev-parse", "--absolute-git-dir") == common
            or git(source, "rev-parse", "--show-toplevel") != str(source)):
        raise UsageError("Use the isolated task writer, never a shared/main checkout, for a release handoff.", {})
    if git(source, "status", "--porcelain=v1", "-z", "--untracked-files=no"):
        raise UsageError("The approved source has staged or unstaged changes. Preserve them and obtain the actual unchanged reviewed head before release.", {})
    if git(source, "branch", "--show-current") not in (branch, ""):
        raise UsageError("The source checkout changed branch; preserve its actual owner rather than detaching unrelated work.", {})
    intent_name = "foreman-release-" + hashlib.sha256(str(target).encode()).hexdigest() + ".json"
    intent_path = Path(common) / intent_name
    existing = intent_path.exists() or intent_path.is_symlink()
    if not existing:
        release_activation.require("clean release-checkout handoff")
    _pushed_head(source, branch, head)
    for key in ("base_revision", "fetched_default_revision"):
        provision.ensure_commit(source, original[key], base_revision=registered["base_revision"])
    provision.require_ancestor(source, registered["base_revision"])
    if intent_path.exists() or intent_path.is_symlink():
        intent = _read(intent_path)
        expected = {"state_path": str(Path(state_path).resolve()), "task": task, "source": str(source),
                    "path": str(target), "branch": branch, "head": head, "base_revision": registered["base_revision"],
                    "source_provenance": original, "binding": authority._binding(supervised)}
        if any(intent[key] != value for key, value in expected.items()):
            raise UsageError("The existing checkout intent names different task/head/owner evidence. Preserve it and reconcile its original handoff.", {})
        evidence = intent["evidence"]
        if evidence["kind"] == "ledger":
            _ready_ledger(ledger, state_path, task, registered["base_revision"], head)
            if str(Path(ledger).resolve()) != evidence["receipt"]["path"]:
                raise UsageError("Retry with the original ready-for-release ledger, preserving its recorded prefix.", {})
            _prefix(evidence["receipt"])
        else:
            old = evidence["grant"]
            current = authority.current_grant(state, task)
            expected = release_rebind.expected_grant(evidence, evidence["successor"], intent["at"])
            if current == old:
                checked, _ = release_rebind.prepare(state_path, state, supervised, task, source, target, head, plugin_root, recorded=True)
                if checked != {key: value for key, value in evidence.items() if key != "successor"}:
                    raise UsageError("The original workflow handoff evidence changed; preserve all owners and reconcile the existing intent.", {})
            elif current != expected:
                raise UsageError("Task authority changed after this checkout intent; preserve the newer owner and the retained source.", {})
    else:
        if git(source, "branch", "--show-current") != branch:
            raise UsageError("The source is detached without this owner's recorded handoff. Preserve it and reconcile its original task branch before preparing a successor.", {})
        if target.exists() or target.is_symlink():
            raise UsageError("The selected successor already exists without this owner's prior intent. Preserve every existing file and choose a fresh path.", {})
        evidence, replacement = release_rebind.prepare(state_path, state, supervised, task, source, target, head, plugin_root)
        if evidence is None:
            latest = recovery.latest_assignment(state["assignments"], task=task, role="developer", status="applied")
            dispatch = next((row for row in state["recovery"]["dispatches"] if latest is not None
                             and row["task"] == task and row["role"] == "developer" and row["assignment_index"] == latest[0]), None)
            if dispatch is None or _writer_path(dispatch, branch=branch) != str(source):
                raise UsageError("The selected source is not bound by this task's actual latest developer assignment; recover its original provenance before moving a branch.", {})
            member = next((row for row in supervised["members"] if row["id"] == dispatch["id"]), None)
            if member is None:
                raise UsageError("Restore the original developer enrollment before moving this task's branch.", {})
            workflow_adoption.brief_evidence(dispatch, supervision.expected_assignment(member))
            evidence = {"kind": "ledger", "receipt": _ready_ledger(ledger, state_path, task, registered["base_revision"], head)}
        else:
            contract_path = Path(evidence["grant"]["contract"]["path"]).with_name("release-contract-" + hashlib.sha256(str(target).encode()).hexdigest()[:24] + ".json")
            _publish(contract_path, replacement)
            evidence["successor"] = workspace.capture(contract_path)[0]
        intent = {"schema_version": SCHEMA_VERSION, "state_path": str(Path(state_path).resolve()), "task": task,
                  "source": str(source), "path": str(target), "branch": branch, "head": head,
                  "base_revision": registered["base_revision"], "source_provenance": deepcopy(original),
                  "evidence": evidence, "binding": authority._binding(supervised), "at": at, "authorizes_release": False}
    generation = _execute(state_path, state, intent_path, intent, client, new=not existing)
    preserved = intent["evidence"].get("progress", {}).get("exception")
    if generation is not None and preserved is not None:
        from .workflow_recovery import resume
        current, _usable = load_state_checked(state_path, persist_migration=False)
        if current["recovery"]["tasks"][task]["progression"]["exception"] == preserved:
            # This is the existing exact-packet resume owner, under the same
            # task's already admitted release scope, never a new decision.
            resume(state_path, {"task": task, "expected_generation": generation,
                "exception": supervision.digest(preserved), "authorization": registered["authorization"]},
                at, client, plugin_root)
        current, _usable = load_state_checked(state_path, persist_migration=False)
        preserved = current["recovery"]["tasks"][task]["progression"]["exception"]
    return {"schema_version": 1, "task": task, "path": str(target), "branch": branch, "head": head,
            "retained_source": str(source), "intent": str(intent_path), "generation": generation,
            "exception_preserved": bool(preserved),
            "authorizes_release": False}


def _task_snapshot(state, task):
    """Selected task only; fresh commit reloads preserve independent changes."""
    return supervision.digest({"task": state["recovery"]["tasks"][task],
        "assignments": [row for row in state["assignments"] if row.get("task") == task],
        "assessments": [row for row in state["specialist_assessments"] if row.get("task") == task],
        "recovery": {key: [row for row in value if isinstance(row, dict) and row.get("task") == task]
                     for key, value in state["recovery"].items() if isinstance(value, list)}})


def _execute(state_path, snapshot, intent_path, intent, client, *, new):
    if new:
        release_activation.require("clean release-checkout handoff")
    elif _read(intent_path) != intent:
        raise UsageError("Resume only the exact original owner-written checkout intent; caller data cannot bypass activation.", {})
    task, source, target = intent["task"], Path(intent["source"]), Path(intent["path"])
    original, branch, head = intent["source_provenance"], intent["branch"], intent["head"]
    common = str(intent_path.parent)
    expected = _task_snapshot(snapshot, task)
    grant = authority.current_grant(snapshot, task)
    body = (json.dumps(intent, indent=2) + "\n").encode()
    captured = ({"path": str(intent_path), "sha256": hashlib.sha256(body).hexdigest()} if new
                else workspace.capture(intent_path)[0])
    generation = grant["generation"] if grant is not None else 0
    locator = {"schema_version": 1, "state_path": str(Path(state_path).resolve()), "task": task,
        "intent": captured, "ready": str(intent_path) + ".ready", "generation": generation,
        "task_sha256": release_flight.task_fingerprint(snapshot["recovery"]["tasks"][task], intent["binding"])}
    # A replay after the primary commit retains the original starting generation.
    if intent["evidence"]["kind"] == "workflow":
        locator["generation"] = intent["evidence"]["grant"]["generation"]
    location = release_flight.locator_path(state_path, task)
    lease_path = grant["lease_path"] if grant is not None and grant["mode"] == "service" else str(location) + ".lock"

    def current():
        state = authority._load(state_path)
        task_evidence.require_clear(state, {task})
        if _task_snapshot(state, task) != expected:
            raise UsageError("This task changed during checkout preparation. Preserve the exact intent and newer owner evidence; independent task changes are retained.", {})
        return state

    def checked(state, present):
        if authority._binding(present) != intent["binding"] or authority._unresumed_hold(present):
            raise UsageError("The foreman binding or operator hold changed; preserve this exact checkout intent and its resume condition.", {})
        authority._settled(state, present, task)
        _writers_clear(state, present, task, source)

    def ready_record():
        ready = {key: locator[key] for key in ("schema_version", "state_path", "task", "intent", "generation", "task_sha256")}
        if intent["evidence"]["kind"] == "workflow":
            ready["generation"] += 1
        ready["authorizes_progression"] = False
        return ready

    with process_lease(lease_path):
        # Publish only the tiny locator under the shared owners, before any
        # checkout mutation. No Git/native call occurs in either transaction.
        with state_lock(state_path):
            state = current()
            def arm(present):
                checked(state, present)
                if location.exists() or location.is_symlink():
                    facts = release_flight.inspect(state_path, state, task)
                    recorded = release_flight._read(location, task, release_flight.LOCATOR_BYTES)
                    if facts is None or facts["intent"] != captured or recorded is None or recorded[0] != locator:
                        raise UsageError("Another checkout intent owns this task's flight locator. Preserve it and resume only that exact transaction.", {})
                elif not new:
                    completed = release_flight._read(Path(locator["ready"]), task, release_flight.LOCATOR_BYTES, absent=True)
                    if completed is None or completed[0] != ready_record():
                        raise UsageError("An unarmed checkout intent has no task-facts locator or matching ready receipt. Preserve it and choose a fresh target through normal preparation; do not infer an earlier Git outcome.", {})
                if new:
                    _publish(intent_path, intent)
                _publish(location, locator)
            supervision.transaction(state_path, arm)
        # No force flag, file cleanup, reset or branch deletion is permitted.
        if target.exists() or target.is_symlink():
            _owned(target, directory=True)
            if (git(target, "rev-parse", "--path-format=absolute", "--git-common-dir") != common
                    or git(target, "rev-parse", "--show-toplevel") != str(target)):
                raise UsageError("The successor path belongs to another repository. Preserve its complete checkout and original handoff intent.", {})
        else:
            if git(source, "branch", "--show-current") == branch:
                git(source, "switch", "--detach", head)
            git(source, "worktree", "add", str(target), branch)
        if git(source, "branch", "--show-current") or git(target, "branch", "--show-current") != branch:
            raise UsageError("Keep the retained source detached and its clean successor on the original feature branch; preserve changed checkouts.", {})
        _pushed_head(target, branch, head)
        if git(target, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
            raise UsageError("The successor contains local work. Preserve it unchanged; release still requires an actually clean checkout.", {})
        provision.record(target, branch, original["base_ref"], original["base_revision"],
                         original["fetched_default_ref"], original["fetched_default_revision"])
        if intent["evidence"]["kind"] == "workflow":
            from .progression_service import capture_contract
            _captured, document = capture_contract(intent["evidence"]["successor"]["path"])
            if workspace.inspect(document, snapshot["recovery"]["tasks"][task], built=True) != intent["evidence"]["progress"]["head"]:
                raise UsageError("The successor's actual commit/tree/paths differ from the verified source; preserve it for current verification.", {})
        successor_receipt = receipt_path(target)
        # Refresh native identity and other current scopes without holding a
        # global lock; the commit rechecks binding/holds against fresh owners.
        present = authority.verify_foreman(state_path, client, native_only=True)
        _writers_clear(snapshot, present, task, source)
        with state_lock(state_path):
            state = current()
            def commit(present):
                checked(state, present)
                completed_generation = release_rebind.commit(state_path, state, intent)
                _publish(successor_receipt, intent)
                _publish(Path(locator["ready"]), ready_record())
                facts = release_flight.inspect(state_path, state, task)
                if facts is None or facts["pending"] or facts["intent"] != captured:
                    raise UsageError("Retain this exact unsettled checkout locator for owner readback; no effect authority is inferred.", {})
                # This owner removes only its matching, proved completed fence.
                recorded = release_flight._read(location, task, release_flight.LOCATOR_BYTES)
                if recorded is None or recorded[0] != locator:
                    raise UsageError("The checkout locator changed before retirement; preserve both owners' evidence.", {})
                try:
                    location.unlink()
                except OSError:
                    raise StateError("The proved ready checkout retains its exact flight locator. Restore owner-directory access and retry this intent; do not delete unknown metadata.", {}) from None
                return completed_generation
            return supervision.transaction(state_path, commit)


def read(path, state_path, task):
    """Read a private owner locator; no receipt alone supplies role authority."""
    location = receipt_path(path)
    value = _read(location)
    if (value.get("state_path") != str(Path(state_path).resolve()) or value.get("task") != task
            or value.get("path") != str(Path(path).resolve()) or value.get("authorizes_release") is not False):
        raise UsageError("Restore the release checkout receipt matching this exact task and owner; unsupported or foreign receipts confer no authority.", {})
    return value


def original_scope(document, state_path, state):
    """Prove a current successor before interpreting its unchanged source receipt.

    A same-named branch, caller override or copied contract supplies no bridge.
    Both immutable Git-owner copies and the current generation must match.
    No original history/native transcript is rewritten or reconstructed here.
    """
    target = Path(document["repository"]["worktree"])
    location = receipt_path(target)
    if not location.exists() and not location.is_symlink():
        return None
    intent = read(target, state_path, document["task"])
    task = recovery.task_record(state["recovery"], document["task"])
    task_evidence.require_clear(state, {document["task"]})
    evidence = intent["evidence"]
    if evidence["kind"] != "workflow" or intent["base_revision"] != task["base_revision"]:
        raise UsageError("This checkout receipt does not bind the original adopted task and workflow base; preserve its source scope.", {})
    common = Path(git(target, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    private_intent = common / ("foreman-release-" + hashlib.sha256(str(target).encode()).hexdigest() + ".json")
    if _read(private_intent) != intent:
        raise UsageError("The successor's private receipt differs from its original common-Git intent; preserve both and reconcile the actual owner.", {})
    from .progression_service import capture_contract
    from .workflow_contract import contract, validate_current
    original, declaration = capture_contract(evidence["grant"]["contract"]["path"])
    successor, current = capture_contract(evidence["successor"]["path"])
    expected = deepcopy(declaration)
    expected["repository"]["worktree"] = str(target)
    grant = authority.current_grant(state, document["task"])
    if (grant is None or original != evidence["grant"]["contract"] or successor != evidence["successor"]
            or current != document or current != expected
            or grant != release_rebind.expected_grant(evidence, successor, intent["at"])):
        raise UsageError("Restore both original/successor immutable contracts and their exact current grant generation; a checkout receipt cannot replace authority.", {})
    contract(declaration, task)
    contract(document, task)
    validate_current(task["progression"], document)
    if (task["progression"]["generation"] != grant["generation"] or grant["binding"] != intent["binding"]
            or authority._binding(supervision.load(state_path)) != intent["binding"]):
        raise UsageError("Restore this successor's admitted task generation and foreman binding before interpreting its original source scope.", {})
    source = Path(intent["source"])
    _owned(source, directory=True)
    _owned(provision.receipt_path(source))
    try:
        if provision.receipt_path(source).stat().st_size > MAX_BYTES:
            raise ValueError()
        source_provenance = provision.validate(json.loads(provision.receipt_path(source).read_text()))
    except (OSError, ValueError):
        raise StateError("Restore the retained source's original provisioning receipt before continuing its adopted task.", {}) from None
    if (source_provenance != intent["source_provenance"] or declaration["repository"]["worktree"] != str(source)
            or declaration["repository"]["branch"] != intent["branch"]
            or git(source, "rev-parse", "--path-format=absolute", "--git-common-dir") != str(common)
            or git(source, "branch", "--show-current") or git(source, "rev-parse", "HEAD") != intent["head"]
            or git(source, "rev-parse", "--show-toplevel") != str(source)):
        raise UsageError("The original retained source/common repository/head changed; preserve both checkouts and recover their real provenance.", {})
    provision.read(target)
    if workspace.inspect(document, task, built=True) != task["progression"]["head"]:
        raise UsageError("The successor differs from its current accepted task head; retain changed work for its owner before dependent release actions.", {})
    return {"repository": declaration["repository"], "contract": original}


def native_cwd(state_path, task, worktree):
    """Keep the original project bootstrap; only business Git uses a successor.

    No-handoff launches retain their existing worktree cwd. A current owned
    handoff proves the retained source through its immutable Git owner bridge;
    neither caller cwd nor a global plugin installation substitutes for it.
    No new runtime directory, config copy or per-launch history is created.
    """
    location = receipt_path(worktree)
    if not location.exists() and not location.is_symlink():
        return worktree
    intent = read(worktree, state_path, task)
    state = authority._load(state_path)
    grant = authority.current_grant(state, task)
    if grant is None or grant["mode"] != "service" or grant.get("contract_schema") not in (2, 3):
        raise UsageError("Use the original admitted workflow before selecting a retained startup project; a receipt alone grants no role.", {})
    from .progression_service import capture_contract
    captured, document = capture_contract(grant["contract"]["path"])
    if captured != grant["contract"] or document["repository"]["worktree"] != str(worktree):
        raise UsageError("Restore the exact current workflow and successor before selecting its original project bootstrap.", {})
    original = original_scope(document, state_path, state)
    if original is None or original["repository"]["worktree"] != intent["source"]:
        raise UsageError("The retained startup project differs from the exact owner-written source; preserve both checkouts for provenance recovery.", {})
    return intent["source"]


def register_commands(sub, common):
    parser = sub.add_parser("prepare-release-checkout", parents=[common], help="Preserve a settled dirty source and prepare its clean, same-head release successor through the actual foreman.")
    for name in ("task", "source", "target", "head"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--ledger")
    parser.add_argument("--now")
