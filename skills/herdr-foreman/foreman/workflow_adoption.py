"""Bind existing settled source to verification without inventing a built claim.

The immutable workflow contract retains one versioned adoption interpretation.
Original dispatches, reports, ledgers, native sources and counters remain with
their existing owners. Preparing this receipt grants no runtime authority.
A completed source may transfer its still-active enrollment for independent
verification. That transfer settles delivery supervision, never acceptance.
New admissions stay disabled until both registries publish these readers.
"""

import json
import re
from pathlib import Path

from . import engagement, recovery, report_delivery, report_gates, supervision, task_evidence
from . import workflow_workspace as workspace
from .errors import UsageError



FIELDS = {"schema_version", "dispatch", "report", "native_source", "native_session",
          "dispatch_digest", "enrollment_digest", "head", "correction", "source_status"}


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


def source_scope(document, dispatch):
    """Match the original supported brief's owner-derived writer and branch."""
    _receipt, raw = workspace.capture(dispatch["brief"])
    body = raw.decode("utf-8")
    marker = "## Admitted current task\n\n```json\n"
    repository = document["repository"]
    if body.count(marker) == 1:
        try:
            context = json.loads(body.split(marker, 1)[1].split("\n```", 1)[0])
        except ValueError:
            raise UsageError("Restore the original source brief's owner-derived task context before adoption.", {}) from None
        if (not isinstance(context, dict) or context.get("task") != document["task"] or context.get("repository") != repository):
            raise UsageError("The selected writer differs from the original source assignment; preserve its original task branch and checkout.", {})
        return
    matches = re.findall(r"Your worktree already exists at `([^`\n]+)`, on branch `([^`\n]+)`, provisioned", body)
    if matches != [(repository["worktree"], repository["branch"])]:
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
    source_scope(document, dispatch)
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
    source_scope(document, dispatch)
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
        if resolution["outcome"] != transfer_outcome(document) or not all(any(
                row["path"] == expected["path"] and row["sha256"] == expected["sha256"]
                for row in resolution["evidence"]) for expected in (report, grant["contract"])):
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
