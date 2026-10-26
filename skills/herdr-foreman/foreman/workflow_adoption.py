"""Bind existing settled source to verification without inventing a built claim.

The immutable workflow contract retains one versioned adoption interpretation.
Original dispatches, reports, ledgers, native sources and counters remain with
their existing owners. Preparing this receipt grants no runtime authority.
A completed source may transfer its still-active enrollment for independent
verification. That transfer settles delivery supervision, never acceptance.
New admissions stay disabled until both registries publish these readers.
"""

from copy import deepcopy
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from . import engagement, recovery, report_delivery, report_gates, supervision, task_evidence
from . import workflow_workspace as workspace
from .errors import UsageError



FIELDS = {"schema_version", "dispatch", "report", "native_source", "native_session",
          "dispatch_digest", "enrollment_digest", "head", "correction", "source_status"}
_ADMISSION = object()


def _admission_scope(state, supervised, task):
    """Only selected task facts; unrelated checkpoints must survive admission."""
    return supervision.digest({
        "task": state["recovery"]["tasks"].get(task),
        "assignments": [(index, row) for index, row in enumerate(state["assignments"]) if row.get("task") == task],
        "recovery": {name: [row for row in rows if row.get("task") == task]
                     for name, rows in state["recovery"].items() if isinstance(rows, list)},
        "assessments": [row for row in state["specialist_assessments"] if row.get("task") == task],
        "members": [{key: value for key, value in row.items() if key != "observed"}
                    for row in supervised["members"] if row["assignment"]["task"] == task]})


def _file_stamp(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise UsageError("Restore this task's readable Git metadata before retrying adoption; preserve its source and original owner.", {}) from None
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _git_stamps(document):
    root = Path(document["repository"]["worktree"])
    private = Path(workspace.git(root, "rev-parse", "--absolute-git-dir").strip())
    common = Path(workspace.git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    paths = [root / ".git", private / "HEAD", private / "index", common / "config", common / "packed-refs",
             common / "refs/heads" / document["repository"]["branch"], common / "reftable", common / "reftable/tables.list"]
    # Capture both a locator and its resolved target; replacing either cannot
    # hide a head/index/config change between the outside read and commit.
    try:
        paths = sorted(set(paths) | {path.resolve() for path in paths})
    except (OSError, RuntimeError):
        raise UsageError("Restore the original task checkout paths before preparing adoption; linked or changed Git metadata supplies no current proof.", {}) from None
    return tuple((path, _file_stamp(path)) for path in paths)


def _policy_stamps(plugin_root):
    """Freeze verified policy files without invoking installed lookup at commit."""
    from . import native_policy
    root = Path(plugin_root).resolve()
    if root.name in native_policy.ADAPTERS:
        root = root / "skills" / native_policy.SKILL
    if root.name == native_policy.SKILL:
        project = root.parents[2]
        controls = [project / ".agents/registry.lock", project / "agents.yaml"]
        lock, declaration = (native_policy._read(path) for path in controls)
        selected = native_policy._selection(project, lock, declaration, native_policy.ADAPTERS[root.parent.parent.name], run=subprocess.run)
        paths = [*controls, *(project / relative for relative in selected["targets"])]
    else:
        paths = [root / ".tessl-plugin/plugin.json", *(path for directory in (root / "rules", root / "skills/herdr-foreman")
                 for path in directory.rglob("*") if path.is_file()
                 and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"})]
    # Directory metadata also detects an added or removed policy file.
    parents = {parent for path in paths for parent in path.parents if parent.is_relative_to(root)}
    return tuple((path, _file_stamp(path)) for path in sorted(set(paths) | parents))


def _same_input(expected):
    """Recheck immutable bytes without opening a pipe or unbounded source."""
    descriptor = None
    try:
        path = Path(expected["path"])
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > workspace.INPUT_LIMIT:
            return False
        body = os.read(descriptor, workspace.INPUT_LIMIT + 1)
        current = path.lstat()
        return (len(body) <= workspace.INPUT_LIMIT and str(path.resolve()) == expected["path"]
                and (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino)
                and hashlib.sha256(body).hexdigest() == expected["sha256"])
    except (OSError, RuntimeError):
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_local_head(document, expected):
    """Bounded local Git identities; no network, native session or policy lookup."""
    prefix = ["git", "-c", "core.fsmonitor=false", "--no-optional-locks", "--no-pager", "-C", document["repository"]["worktree"]]
    results = []
    try:
        for args in (("rev-parse", "--show-toplevel", "HEAD", "HEAD^{tree}"), ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
                     ("branch", "--show-current"), ("remote", "get-url", "--all", "origin"),
                     ("remote", "get-url", "--push", "--all", "origin")):
            result = subprocess.run([*prefix, *args], capture_output=True, timeout=2, check=False)
            if result.returncode or len(result.stdout) > workspace.INPUT_LIMIT:
                raise UsageError("Restore this task's bounded readable local Git state before retrying adoption; preserve all source files.", {})
            results.append(result.stdout)
    except (OSError, subprocess.TimeoutExpired):
        raise UsageError("The local task checkout could not be rechecked within its short admission budget; preserve the owner and inspect that checkout before retrying.", {}) from None
    try:
        head = results[0].decode("utf-8").splitlines()
        branch = results[2].decode("utf-8").strip()
        fetch, push = (result.decode("utf-8").splitlines() for result in results[3:])
    except UnicodeDecodeError:
        raise UsageError("Restore the task's readable UTF-8 local checkout, branch and origin URLs before retrying adoption; preserve its current configuration.", {}) from None
    try:
        same_root = len(head) == 3 and Path(head[0]).resolve() == Path(document["repository"]["worktree"]).resolve()
    except (OSError, RuntimeError):
        raise UsageError("Restore the task's actual readable checkout path before retrying adoption; preserve its current files and configuration.", {}) from None
    if results[1] or not same_root or head[1:] != [expected["commit"], expected["tree"]]:
        raise UsageError("The writer changed or became dirty after source verification; preserve the new source and prepare the same task again.",
                         {"reason": "adoption_evidence_changed"})
    target = document["repository"]["github"].casefold()
    identities = [workspace.origin_identity(url) for url in (*fetch, *push)]
    if (branch != document["repository"]["branch"] or not fetch or not push
            or any(identity is None or identity.casefold() != target for identity in identities)):
        raise UsageError("The effective task branch or fetch/push repository changed after verification; preserve the configuration and restore its authorized targets before retrying adoption.",
                         {"reason": "adoption_evidence_changed"})


class _Admission:
    """In-process verified preparation, never serialized or caller authority."""

    def __init__(self, key, state_path, data, at, plugin_root, state, supervised, captured, document, source, policy, policy_files, inputs, git):
        if key is not _ADMISSION:
            raise UsageError("Prepare adoption through its current owner before committing its handoff.", {})
        self.state_path, self.plugin_root = Path(state_path).resolve(), Path(plugin_root).resolve()
        self.request = supervision.digest([data, at])
        self.scope = _admission_scope(state, supervised, data["task"])
        self.binding = deepcopy(supervised["binding"])
        self.contract, self.document, self.source = captured, deepcopy(document), deepcopy(source)
        self.policy_files = policy_files
        self.policy, self.inputs, self.git = policy, inputs, git

    def require_request(self, state_path, data, at, plugin_root):
        if (Path(state_path).resolve() != self.state_path or Path(plugin_root).resolve() != self.plugin_root
                or self.request != supervision.digest([data, at])):
            raise UsageError("Retry only this verified adoption's exact owner, contract and authorization; changed requests need fresh preparation.", {})

    def recheck(self, state, supervised):
        """Bounded local receipts, Git and owner facts; no remote/native lookup."""
        task = self.document["task"]
        _require_local_head(self.document, self.source["head"])
        if (supervised["binding"] != self.binding or _admission_scope(state, supervised, task) != self.scope
                or any(_file_stamp(path) != expected for path, expected in (*self.git, *self.policy_files))):
            raise UsageError("Adoption authority, source or Git facts changed during verification; preserve the current owner and prepare the same task again.",
                             {"reason": "adoption_evidence_changed"})
        for expected in [self.contract, *self.inputs]:
            if not _same_input(expected):
                raise UsageError("An adoption input changed during verification; preserve its original bytes and prepare the same task again.",
                                 {"reason": "adoption_evidence_changed"})
        report_gates.require_clear(self.state_path, self.source["report"]["path"], True)
        return self.source


def prepare_admission(state_path, data, at, client, plugin_root):
    """Verify source outside the shared transaction, then retain no disk state."""
    from . import policy_paths, progression_owner as authority, release_activation, workflow_contract
    from .progression_service import capture_contract
    from .state import state_lock
    release_activation.require("legacy task adoption")
    with state_lock(state_path):
        state = authority._load(state_path)
        supervised = supervision.load(state_path)
    policy_files = _policy_stamps(plugin_root)
    policy = authority.loaded_policy(plugin_root)
    if _policy_stamps(plugin_root) != policy_files:
        raise UsageError("Policy changed while its adoption identity was being verified; preserve the current owner and retry from the unchanged installed policy.",
                         {"reason": "adoption_evidence_changed"})
    authority.verify_foreman(state_path, client, native_only=True, supervised=supervised)
    captured, document = capture_contract(data["contract"])
    row = recovery.task_record(state["recovery"], data["task"])
    workflow_contract.contract(document, row)
    if document["schema_version"] != 3:
        raise UsageError("Prepare only this existing task's versioned adoption contract; a fresh workflow needs its own admission.", {})
    task_evidence.require_clear(state, {data["task"]})
    from .release_flight import require_clear
    require_clear(state_path, state, {data["task"]})
    if authority._unresumed_hold(supervised):
        raise UsageError("Existing operator holds prevent service admission; preserve their explicit resume conditions.", {})
    git = _git_stamps(document)
    workspace.inputs(document)
    policy_paths.brief_inputs(Path(__file__).resolve().parents[1], workspace.base_checkout(document),
        Path.home() / ".tessl", os.environ.get("HERDR_CODING_POLICY_ROOT") or None, workflow=True)
    source = require_current(state_path, state, supervised, document, client)
    dispatch = next(item for item in state["recovery"]["dispatches"] if item["id"] == source["dispatch"])
    inputs = [document["config"], document["common"], *document["briefs"].values(), source["report"], source["native_source"],
              *[workspace.capture(dispatch[name])[0] for name in ("common", "brief")]]
    return _Admission(_ADMISSION, state_path, data, at, plugin_root, state, supervised, captured,
                      document, source, policy, policy_files, inputs, git)


def validate(value):
    if (not isinstance(value, dict) or set(value) != FIELDS
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["dispatch"], str) or not value["dispatch"]
            or type(value["correction"]) is not int or value["correction"] < 0
            or not isinstance(value["source_status"], str) or value["source_status"] not in {"reported", "accepted"}):
        raise UsageError("Restore the supported immutable legacy adoption receipt; never relabel existing work as a new implementation.", {})
    for name in ("report", "native_source"):
        recovery.validate_receipt(value[name])
    for name in ("dispatch_digest", "enrollment_digest"):
        if not isinstance(value[name], str) or len(value[name]) != 64 or any(char not in "0123456789abcdef" for char in value[name]):
            raise UsageError("Preserve the canonical legacy dispatch and enrollment digests in the adoption receipt.", {})
    if value["native_session"] is None or report_delivery.native_identity({"agent_session": value["native_session"]}) != value["native_session"]:
        raise UsageError("Retain the original source assignment's exact native identity before adoption.", {})
    from .workflow_contract import validate_head
    validate_head(value["head"])


def brief_evidence(dispatch, expected):
    paths = {"common": dispatch["common"], dispatch["role"]: dispatch["brief"]}
    contents = {path: workspace.capture(path)[1] for path in paths.values()}
    if recovery.brief_identity(paths, dispatch["role"], expected["report"], contents) != dispatch["brief_identity"]:
        raise UsageError("Restore the original dispatched brief bytes and report identity before adoption.", {})
    return contents


def source_evidence(state_path, state, member, dispatch, *, check_gates=True):
    """Authenticate the actual dispatched turn, independently of report assessment."""
    from .assign import assignment_text, tiered_prompt
    expected = supervision.expected_assignment(member)
    task_evidence.require_clear(state, {expected["task"]})
    if (dispatch["status"] != "applied" or dispatch["result"] is None
            or any(dispatch[key] != expected[key] for key in ("task", "agent"))):
        raise UsageError("Restore the original applied dispatch and enrolled source identity before adoption.", {})
    native = report_delivery.native_identity({"agent_session": expected["native_session"]})
    if native is None:
        raise UsageError("Restore this source enrollment's exact native session before adoption.", {})
    report, _body = workspace.capture(expected["report"], limit=workspace.REPORT_LIMIT)
    report_delivery.require_primary_delivery(dispatch, state["assignments"][dispatch["assignment_index"]],
                                            expected, expected["report"])
    contents = brief_evidence(dispatch, expected)
    source_path = report_delivery.source_path(native)
    if source_path is None:
        raise UsageError("Restore the original native final-source proof before adopting this delivery.", {})
    source, body = workspace.capture(source_path)
    text = body.decode("utf-8")
    prompt = assignment_text(dispatch["role"], dispatch["common"], dispatch["brief"])
    tier = dispatch["result"].get("tier")
    if isinstance(tier, dict):
        prompt, digest = tiered_prompt(prompt, tier, dispatch["common"], dispatch["brief"], contents)
        if tier.get("prompt_hash") != digest:
            raise UsageError("Restore the original native prompt/model receipt before source adoption.", {})
    if (not report_delivery.prompt_matches(report_delivery.source_prompt(text, native["agent"], native["value"], path=source_path), prompt, native["agent"])
            or not report_delivery.bare_final(report_delivery.source_final(text, native["agent"], native["value"], path=source_path), expected["report"])):
        raise UsageError("The native source does not prove this exact dispatched prompt and completed report; preserve its original obligation.", {})
    if check_gates:
        report_gates.require_clear(state_path, report["path"], True)
    return report, source, native


def source_scope(document, dispatch, *, state_path=None, state=None):
    """Match the original writer, or its exact settled Git-owner successor."""
    _receipt, raw = workspace.capture(dispatch["brief"])
    body = raw.decode("utf-8")
    marker = "## Admitted current task\n\n```json\n"
    compiled = body.count(marker) == 1
    context_repository, pairs = None, []
    if compiled:
        try:
            context = json.loads(body.split(marker, 1)[1].split("\n```", 1)[0])
        except ValueError:
            raise UsageError("Restore the original source brief's owner-derived task context before adoption.", {}) from None
        if not isinstance(context, dict) or context.get("task") != document["task"]:
            raise UsageError("The selected writer differs from the original source assignment; preserve its original task branch and checkout.", {})
        context_repository = context.get("repository")
    else:
        pairs = re.findall(r"Your worktree already exists at `([^`\n]+)`, on branch `([^`\n]+)`, provisioned", body)

    def matches(repository):
        return (context_repository == repository if compiled else
                pairs == [(repository["worktree"], repository["branch"])])

    if matches(document["repository"]):
        return None
    if state_path is not None and state is not None:
        from .release_checkout import original_scope
        original = original_scope(document, state_path, state)
        if original is not None and matches(original["repository"]):
            return original
    raise UsageError("The original source brief does not bind this supported writer/branch; recover its real checkout provenance through the task owner before adoption.", {})


def prepare(state_path, state, supervised, document, identifier, *, client=None):
    task = document["task"]
    latest = recovery.latest_assignment(state["assignments"], task=task, role="developer", status="applied")
    dispatch = next((row for row in state["recovery"]["dispatches"] if row["id"] == identifier), None)
    member = next((row for row in supervised["members"] if row["id"] == identifier), None)
    if (latest is None or dispatch is None or dispatch["task"] != task or dispatch["role"] != "developer"
            or dispatch["status"] != "applied" or dispatch["assignment_index"] != latest[0]
            or member is None):
        raise UsageError("Adopt the actual latest applied developer assignment under its original enrollment; unknown sends and missing provenance retain their existing owner.",
                         {"reason": "legacy_source_provenance_required"})
    report, source, native = source_evidence(state_path, state, member, dispatch)
    source_scope(document, dispatch, state_path=state_path, state=state)
    if member["active"]:
        if client is None:
            raise UsageError("Authenticate the completed source with the exact native foreman before transferring its active enrollment.", {})
        expected = supervision.expected_assignment(member)
        live = client.agent_get(expected["agent"])
        if (live.get("pane_id") != expected["pane_id"] or report_delivery.native_identity(live) != native
                or live.get("agent_status") not in ("idle", "done")):
            raise UsageError("The original source is not currently completed in its enrolled native session; preserve the active obligation.", {})
        status = "reported"
    else:
        from .progression_service import ProgressionService
        refusal = ProgressionService.closed_dependency(state_path, state, member)
        if refusal is not None:
            raise UsageError(refusal["message"], {"reason": refusal["code"]})
        engagement.require_accepted(state, identifier, report["path"])
        status = "accepted"
    head = workspace.inspect(document, state["recovery"]["tasks"][task], built=True)
    _receipt, delivered_body = workspace.capture(report["path"], limit=workspace.REPORT_LIMIT)
    tokens = re.findall(r"\b[0-9a-f]{7,64}\b", delivered_body.decode("utf-8"))
    matching = [value for value in tokens if head["commit"].startswith(value)]
    if (not matching or workspace.git(document["repository"]["worktree"],
            "rev-parse", "--disambiguate=" + max(matching, key=len)).splitlines() != [head["commit"]]):
        raise UsageError("The original delivered report does not identify the exact current source head; preserve the report and obtain its owner's source-provenance recovery rather than inventing a built claim.", {})
    remote = workspace.git(document["repository"]["worktree"], "ls-remote", "--exit-code", "origin",
                           "refs/heads/" + document["repository"]["branch"]).splitlines()
    if len(remote) != 1 or remote[0].split("\t") != [head["commit"], "refs/heads/" + document["repository"]["branch"]]:
        raise UsageError("Push and reconcile this exact source head before adoption; a report cannot substitute for the current remote branch.", {})
    return {"schema_version": 1, "dispatch": identifier, "report": report, "native_source": source,
            "native_session": native, "dispatch_digest": supervision.digest({key: value for key, value in dispatch.items() if key != "report"}),
            "enrollment_digest": supervision.digest(supervision.expected_assignment(member)), "head": head, "source_status": status,
            "correction": recovery.confirmed_fix(state["assignments"], task)}


def require_current(state_path, state, supervised, document, client):
    recorded = document.get("adoption")
    validate(recorded)
    current = prepare(state_path, state, supervised, document, recorded["dispatch"], client=client)
    if current != recorded:
        raise UsageError("Legacy source, head or provenance changed after preparation; preserve the original receipt and obtain a fresh owner handoff.",
                         {"reason": "adoption_evidence_changed"})
    return current


def transfer_outcome(document):
    return "Workflow adoption {}: transferred_for_verification".format(supervision.digest(document["adoption"]))


def dependencies(state_path, state, supervised, document):
    """Retain original source proof after its delivery obligation transfers."""
    recorded = document["adoption"]
    validate(recorded)
    dispatch = next((row for row in state["recovery"]["dispatches"] if row["id"] == recorded["dispatch"]), None)
    member = next((row for row in supervised["members"] if row["id"] == recorded["dispatch"]), None)
    if (dispatch is None or member is None
            or supervision.digest({key: value for key, value in dispatch.items() if key != "report"}) != recorded["dispatch_digest"]
            or supervision.digest(supervision.expected_assignment(member)) != recorded["enrollment_digest"]):
        raise UsageError("Restore the adopted source's original enrollment and dispatch provenance before continuing.", {})
    expected = supervision.expected_assignment(member)
    task_evidence.require_clear(state, {expected["task"]})
    brief_evidence(dispatch, expected)
    original = source_scope(document, dispatch, state_path=state_path, state=state)
    report, _body = workspace.capture(expected["report"], limit=workspace.REPORT_LIMIT)
    native = report_delivery.native_identity({"agent_session": expected["native_session"]})
    resolution = member["resolution"]
    if (member["active"] or resolution is None or report != recorded["report"]
            or native != recorded["native_session"]):
        raise UsageError("Preserve the adopted source's original closed native provenance before continuation.", {})
    if recorded["source_status"] == "reported":
        grant = state["recovery"]["tasks"][document["task"]].get("authority")
        if grant is None or grant["contract_schema"] != 3:
            raise UsageError("Restore this source transfer's immutable admitted contract receipt before continuation.", {})
        transfer_contract = original["contract"] if original is not None else grant["contract"]
        if resolution["outcome"] != transfer_outcome(document) or not all(any(
                row["path"] == expected["path"] and row["sha256"] == expected["sha256"]
                for row in resolution["evidence"]) for expected in (report, transfer_contract)):
            raise UsageError("Restore the original source-transfer receipt; delivery transfer supplies no implementation approval.", {})
    else:
        from .progression_service import ProgressionService
        refusal = ProgressionService.closed_dependency(state_path, state, member, native_source_required=False)
        if refusal is not None:
            raise UsageError(refusal["message"], {"reason": refusal["code"]})
    report_gates.require_clear(state_path, report["path"], True)
    return report


def register_commands(sub, common):
    parser = sub.add_parser("progression-prepare-adoption", parents=[common])
    parser.add_argument("--contract", required=True)
    parser.add_argument("--dispatch", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--now")


def run_command(args, state_path, client):
    from . import progression_owner as authority, workflow_contract
    from .progression_service import capture_contract
    state = authority._load(state_path)
    supervised = authority.verify_foreman(state_path, client, native_only=True)
    _captured, document = capture_contract(args.contract)
    if "adoption" in document:
        raise UsageError("Prepare from the original unadopted declaration; preserve an existing immutable adoption contract.", {})
    workflow_contract.contract(document, recovery.task_record(state["recovery"], document["task"]))
    document["adoption"] = prepare(state_path, state, supervised, document, args.dispatch, client=client)
    document["schema_version"] = 3
    target = Path(args.output)
    if not target.is_absolute():
        raise UsageError("Choose an absolute fresh output path for the immutable adopted contract.", {})
    try:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(document, sort_keys=True, indent=2) + "\n")
    except OSError:
        raise UsageError("Cannot exclusively create the adopted contract; preserve existing inputs and select a fresh owner-controlled path.", {}) from None
    return {"task": document["task"], "contract": workspace.capture(target)[0],
            "phase": "verify", "correction": document["adoption"]["correction"],
            "source_assessment": document["adoption"]["source_status"], "authorizes_dispatch": False}
