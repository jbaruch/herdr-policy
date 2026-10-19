"""Schema-2 task workflows and source-bound worker claims.

One immutable admission contract selects responsibilities and permitted effects.
One current schema-2 progression record lives on the existing task. These pure
validators do not admit work, read a pane, accept a report or invoke an effect.
Native delivery, independent identity, current Git facts, classifier gates and
the generic release owner remain mandatory at the executing boundary.
"""

from pathlib import Path
import re

from . import recovery, report_contract, workflow_profiles
from .errors import UsageError
from .chronology import timestamp


VERSION = 2
ROLES = frozenset({"developer", "reviewer", "tester", "release"})
EFFECTS = frozenset({"write", "push", "open_pr", "merge", "publish"})
REVIEW_CONTEXT = workflow_profiles.CORRECTION_FIELDS - {"authority_current", "evidence_current"}
CONTRACT_FIELDS = frozenset({"schema_version", "task", "risk", "repository", "config", "common",
                             "briefs", "artifact_directory", "effects", "publication", "acceptance"})
CLAIM_FIELDS = frozenset({"schema_version", "task", "head_revision", "responsibilities", "outcome",
                          "acceptance", "checks", "findings", "correction", "pull_request", "review_snapshot",
                          "review_evidence", "publication"})
PROGRESS_FIELDS = frozenset({"schema_version", "generation", "phase", "round", "pending", "jobs",
                             "head", "blockers", "exception", "at", "publication_baseline", "plan", "delivery"})
JOB_FIELDS = frozenset({"schema_version", "id", "role", "agent", "worker_kind", "tier", "status", "pane_id",
                        "native_session", "report", "brief", "at", "transport", "report_evidence", "claim"})
JOB_STATES = ("prepared", "starting", "ready", "sending", "running", "delivered", "closed", "not_sent", "uncertain")
PHASES = frozenset({"implement", "verify", "release", "merge", "publish", "cleanup", "complete", "exception"})
OUTCOMES = {"developer": ("built", "blocked"), "reviewer": ("verified", "blocking", "blocked"),
            "tester": ("verified", "blocking", "blocked"), "release": ("ready", "delivered", "blocking", "blocked")}


def _object(value, fields, label, version=VERSION):
    if (not isinstance(value, dict) or set(value) != fields
            or type(value.get("schema_version")) is not int or value["schema_version"] != version):
        raise UsageError("Restore the complete supported {} schema; unknown or missing fields cannot authorize progression.".format(label), {})


def _text(value, label, limit=1024):
    if (not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > limit
            or any(ord(char) < 32 for char in value)):
        raise UsageError("Supply bounded single-line {} from the admitted task, without guessing missing evidence.".format(label), {})
    return value


def _absolute(value, label):
    _text(value, label, 4096)
    if not Path(value).is_absolute():
        raise UsageError("Use the owner's absolute {} path; current working directory cannot select another task.".format(label), {})


def _sha(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?", value) is None:
        raise UsageError("Record the actual full {} Git identity before progression.".format(label), {})


def contract(value, task):
    """Validate the immutable task declaration; return its responsibility profile."""
    _object(value, CONTRACT_FIELDS, "task workflow")
    if value["task"] != task["task"]:
        raise UsageError("Admit the workflow under its original registered task identity and authorization.", {})
    profile = workflow_profiles.select_profile(value["risk"])
    repository = value["repository"]
    if not isinstance(repository, dict) or set(repository) != {"github", "worktree", "branch", "base_branch"}:
        raise UsageError("Bind the workflow to its GitHub repository, actual writer worktree and feature/base branches.", {})
    if (not isinstance(repository["github"], str)
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository["github"]) is None):
        raise UsageError("Use the admitted owner/repository GitHub identity; arbitrary command targets are not workflow inputs.", {})
    _absolute(repository["worktree"], "writer worktree")
    for name in ("branch", "base_branch"):
        _text(repository[name], name, 256)
    if repository["branch"] == repository["base_branch"]:
        raise UsageError("Provision an isolated feature branch; the workflow cannot implement directly on the release base.", {})
    for name in ("config", "common"):
        recovery.validate_receipt(value[name])
    briefs = value["briefs"]
    required = {"developer", "reviewer", "release"} | ({"tester"} if profile["profile"] != "bounded" else set())
    if not isinstance(briefs, dict) or set(briefs) != required:
        raise UsageError("Provide one frozen brief template for every selected responsibility; preserve independent verification.", {})
    for captured in briefs.values():
        recovery.validate_receipt(captured)
    _absolute(value["artifact_directory"], "current workflow artifacts")
    if Path(value["artifact_directory"]).resolve().is_relative_to(Path(repository["worktree"]).resolve()):
        raise UsageError("Keep current owner inputs outside the writer's checkout; implementation cannot replace its own workflow records.", {})
    effects = value["effects"]
    if (not isinstance(effects, list) or any(not isinstance(item, str) for item in effects)
            or len(effects) != len(set(effects)) or not set(effects).issubset(EFFECTS)
            or not {"write", "push", "open_pr", "merge"}.issubset(effects)):
        raise UsageError("Explicitly authorize the workflow's repository, push, PR and merge effects before admission.", {})
    publication = value["publication"]
    if not isinstance(publication, dict) or set(publication) != {"tessl", "acr", "workflow"} or type(publication["acr"]) is not bool:
        raise UsageError("Declare each actual publication channel and its merge-triggered workflow; absence is not a successful publication.", {})
    if publication["tessl"] is not None:
        entry = publication["tessl"]
        if not isinstance(entry, dict) or set(entry) != {"workspace", "plugin"}:
            raise UsageError("Name the admitted Tessl workspace and plugin before publishing.", {})
        for name in ("workspace", "plugin"):
            if not isinstance(entry[name], str) or re.fullmatch(r"[A-Za-z0-9_.-]+", entry[name]) is None:
                raise UsageError("Use literal Tessl workspace/plugin identities from this repository's manifest.", {})
    publishes = publication["tessl"] is not None or publication["acr"]
    if publishes:
        _text(publication["workflow"], "publication workflow", 256)
        if "publish" not in effects:
            raise UsageError("Obtain explicit publication authority for every declared channel before admission.", {})
    elif publication["workflow"] is not None or "publish" in effects:
        raise UsageError("Declare a publication workflow only for an actual publication channel.", {})
    acceptance = value["acceptance"]
    if (not isinstance(acceptance, dict) or set(acceptance) != {"kind", "criteria"}
            or acceptance["kind"] not in ("merge", "deployment", "operator")
            or not isinstance(acceptance["criteria"], list) or not 0 < len(acceptance["criteria"]) <= 16):
        raise UsageError("Declare actual acceptance separately from merge/deployment and list its bounded criteria.", {})
    for criterion in acceptance["criteria"]:
        _text(criterion, "acceptance criterion")
    return profile


def responsibilities(profile, role):
    if role == "developer":
        return ["implementation"]
    if role == "release":
        return ["release"]
    if role == "reviewer":
        return ["review", "tests"] if profile["profile"] == "bounded" else ["review"]
    if role == "tester":
        return ["tests"]
    raise UsageError("Use an admitted outcome, verification or release responsibility.", {})


def claim(body, task, role, profile, head, criteria):
    """Check a native worker's statement against owner-selected scope and role."""
    value = report_contract.workflow_claim(body)
    _object(value, CLAIM_FIELDS, "workflow claim", version=1)
    if (value["task"] != task or value["head_revision"] != head
            or value["responsibilities"] != responsibilities(profile, role)
            or value["outcome"] not in OUTCOMES[role]):
        raise UsageError("The report must bind this dispatch's task, full current head and selected responsibilities; do not adopt another attempt's claim.", {})
    _sha(head, "reviewed head")
    checks = value["checks"]
    if not isinstance(checks, list) or len(checks) > 16:
        raise UsageError("Return a bounded check list; missing or failed checks remain explicit.", {})
    names = set()
    for check in checks:
        if (not isinstance(check, dict) or set(check) != {"responsibility", "name", "result", "evidence"}
                or check["responsibility"] not in value["responsibilities"]
                or check["result"] not in ("passed", "failed", "unavailable")):
            raise UsageError("Each reported check needs its selected responsibility, name, actual result and evidence; unavailable is not passed.", {})
        name = _text(check["name"], "check name", 128)
        _text(check["evidence"], "check evidence")
        if name in names:
            raise UsageError("Name each actual check once; duplicated claims supply no additional coverage.", {})
        names.add(name)
    if value["outcome"] in ("built", "verified", "ready", "delivered") and (not checks or any(item["result"] != "passed" for item in checks)):
        raise UsageError("A built/verified claim needs successful checks; preserve failed and unavailable evidence as an exception.", {})
    if value["outcome"] in ("built", "verified", "ready", "delivered") and {item["responsibility"] for item in checks} != set(value["responsibilities"]):
        raise UsageError("Supply actual successful check evidence for every selected responsibility; combined review cannot omit its independent test coverage.", {})
    verifying = role in ("reviewer", "tester")
    if verifying:
        lines = report_contract.report_lines(body, role)
        stated = "approved" if value["outcome"] == "verified" else "blocking"
        if lines["verdict"] != stated:
            raise UsageError("The workflow statement contradicts the report's owner-parsed VERDICT; record the gap instead of advancing.", {})
        accepted = value["acceptance"]
        if not isinstance(accepted, list) or len(accepted) != len(criteria):
            raise UsageError("Address every admitted acceptance criterion, with evidence, in independent verification.", {})
        for index, item in enumerate(accepted, 1):
            if (not isinstance(item, dict) or set(item) != {"criterion", "state", "evidence"}
                    or type(item["criterion"]) is not int or item["criterion"] != index
                    or item["state"] not in ("met", "unmet")):
                raise UsageError("Report each admitted criterion in order with its actual met/unmet result.", {})
            _text(item["evidence"], "criterion evidence")
        if value["outcome"] == "verified" and any(item["state"] != "met" for item in accepted):
            raise UsageError("Unmet acceptance criteria cannot support a verified claim.", {})
    elif value["acceptance"] is not None:
        raise UsageError("Implementation and release preparation do not provide independent acceptance judgments.", {})
    findings, correction = value["findings"], value["correction"]
    if not isinstance(findings, list) or len(findings) > 32:
        raise UsageError("Keep current finding identities within the workflow budget; preserve the full report for targeted exception handling.", {})
    if verifying or role == "release" and value["outcome"] == "blocking":
        if not isinstance(correction, dict) or set(correction) != REVIEW_CONTEXT:
            raise UsageError("Return explicit scope, cause, uncertainty and convergence facts before routing another correction.", {})
        route = workflow_profiles.correction_route({"schema_version": 1, "authority_current": True,
            "evidence_current": True, **correction}, findings)
        if value["outcome"] == "blocking" and not route["blocking_findings"]:
            raise UsageError("A blocking outcome needs the actual unresolved blocking finding identities.", {})
        if value["outcome"] == "verified" and route["blocking_findings"]:
            raise UsageError("An unresolved blocking finding contradicts verification; preserve the correction obligation.", {})
    elif findings != [] or correction is not None:
        raise UsageError("Return correction judgments only from the independent verification or external-review responsibility.", {})
    if role == "release":
        pr = value["pull_request"]
        if (pr is not None and (type(pr) is not int or pr < 1)
                or value["outcome"] in ("ready", "delivered") and pr is None):
            raise UsageError("Bind release preparation to its actual GitHub PR number.", {})
        snapshot = value["review_snapshot"]
        if ((snapshot is not None and (not isinstance(snapshot, str) or re.fullmatch(r"[a-f0-9]{64}", snapshot) is None))
                or value["outcome"] in ("ready", "delivered") and snapshot is None):
            raise UsageError("Bind the release worker's full review reading to the actual current review snapshot before merge.", {})
        if value["outcome"] == "delivered":
            recovery.validate_receipt(value["review_evidence"])
            publication = value["publication"]
            _object(publication, {"schema_version", "baseline", "baseline_at", "publisher_run", "tag", "tessl_version"}, "release publication claim", version=1)
            if publication["baseline"] is not None:
                if (not isinstance(publication["baseline"], str) or publication["baseline"] != "unpublished"
                        and re.fullmatch(r"\d+\.\d+\.\d+", publication["baseline"]) is None):
                    raise UsageError("Report the actual pre-merge registry baseline from its canonical helper.", {})
                timestamp(publication["baseline_at"], "Pre-merge registry baseline")
            elif publication["baseline_at"] is not None:
                raise UsageError("A baseline time cannot claim a missing registry read.", {})
            if publication["publisher_run"] is not None and (type(publication["publisher_run"]) is not int or publication["publisher_run"] < 1):
                raise UsageError("Report the actual source-bound publisher run, never the latest run.", {})
            for field in ("tag", "tessl_version"):
                if publication[field] is not None:
                    _text(publication[field], "reported publication " + field, 128)
        elif value["review_evidence"] is not None or value["publication"] is not None:
            raise UsageError("Publication evidence belongs to the actual delivered release outcome.", {})
    elif value["pull_request"] is not None or value["review_snapshot"] is not None:
        raise UsageError("Implementation and verification cannot substitute their claim for release review evidence.", {})
    elif value["review_evidence"] is not None or value["publication"] is not None:
        raise UsageError("Only the native release outcome supplies release-reading and publication evidence.", {})
    return value


def initial_progress(generation, at):
    value = {"schema_version": VERSION, "generation": generation, "phase": "implement", "round": 0,
             "pending": None, "jobs": {}, "head": None, "blockers": [], "exception": None,
             "at": at, "publication_baseline": None, "plan": None, "delivery": None}
    validate_progress(value)
    return value


def validate_progress(value):
    """Only the current stage and effect intent; prior dispatch owners retain provenance."""
    _object(value, PROGRESS_FIELDS, "task progression")
    if (type(value["generation"]) is not int or value["generation"] < 1
            or not isinstance(value["phase"], str) or value["phase"] not in PHASES
            or type(value["round"]) is not int or value["round"] < 0):
        raise UsageError("Restore the current owner generation, workflow phase and cumulative correction number.", {})
    timestamp(value["at"], "Workflow stage time")
    if value["plan"] is not None:
        recovery.validate_receipt(value["plan"])
    if value["delivery"] is not None:
        delivery = value["delivery"]
        _object(delivery, {"schema_version", "pull_request", "merge_commit", "publisher_run", "tag",
                           "tessl_version", "tessl_confirmed", "acr_confirmed", "accepted",
                           "base_checkout", "cleanup_step"}, "workflow delivery", version=1)
        if type(delivery["pull_request"]) is not int or delivery["pull_request"] < 1:
            raise UsageError("Keep the actual task PR identity through merge and publication.", {})
        if delivery["merge_commit"] is not None:
            _sha(delivery["merge_commit"], "merged source")
        if delivery["publisher_run"] is not None and (type(delivery["publisher_run"]) is not int or delivery["publisher_run"] < 1):
            raise UsageError("Keep the actual source-bound publication run instead of selecting a latest run.", {})
        for field in ("tag", "tessl_version"):
            if delivery[field] is not None:
                _text(delivery[field], "publication " + field, 128)
        if any(type(delivery[field]) is not bool for field in ("tessl_confirmed", "acr_confirmed", "accepted")):
            raise UsageError("Preserve explicit publication and actual-acceptance facts; unknown evidence cannot become a passing flag.", {})
        _absolute(delivery["base_checkout"], "delivery base checkout")
        if type(delivery["cleanup_step"]) is not int or not 0 <= delivery["cleanup_step"] <= 5:
            raise UsageError("Preserve the current bounded cleanup step; unknown local effects need readback.", {})
        if (delivery["accepted"] and delivery["merge_commit"] is None
                or delivery["tessl_confirmed"] and (delivery["publisher_run"] is None or delivery["tessl_version"] is None)
                or delivery["acr_confirmed"] and (delivery["publisher_run"] is None or delivery["tag"] is None)):
            raise UsageError("Actual acceptance and channel confirmation need their bound merge/run/artifact identities.", {})
    if value["phase"] == "complete" and (value["delivery"] is None or not value["delivery"]["accepted"]):
        raise UsageError("A complete workflow needs its actual accepted delivery, separately from a process exit or merge.", {})
    jobs = value["jobs"]
    if not isinstance(jobs, dict) or not set(jobs).issubset(ROLES):
        raise UsageError("Preserve the current workflow's owner-dispatch identities before recovery.", {})
    for identifier in jobs.values():
        _text(identifier, "canonical dispatch identity", 128)
    pending = value["pending"]
    if pending is not None:
        _object(pending, {"schema_version", "id", "operation", "argv", "inputs", "effects_started", "dispatches", "job"}, "workflow intent")
        _text(pending["id"], "intent identity", 128)
        if (pending["operation"] not in ("measure", "apply", "record", "close", "merge", "cleanup")
                or type(pending["effects_started"]) is not bool
                or not isinstance(pending["argv"], list) or len(pending["argv"]) > 96
                or not isinstance(pending["inputs"], list) or len(pending["inputs"]) > 32
                or not isinstance(pending["dispatches"], list) or len(pending["dispatches"]) > len(ROLES)):
            raise UsageError("Preserve the supported current effect intent; a process exit cannot erase uncertain work.", {})
        for arg in pending["argv"]:
            _text(arg, "owner argument", 4096)
        for captured in pending["inputs"]:
            recovery.validate_receipt(captured)
        for identifier in pending["dispatches"]:
            _text(identifier, "expected dispatch identity", 256)
        if pending["job"] is not None:
            validate_job(pending["job"])
    head = value["head"]
    if head is not None:
        if not isinstance(head, dict) or set(head) != {"commit", "tree", "paths"}:
            raise UsageError("Restore the actual implementation commit, tree and affected paths before verification.", {})
        _sha(head["commit"], "implementation head")
        _sha(head["tree"], "implementation tree")
        if not isinstance(head["paths"], list) or not 0 < len(head["paths"]) <= 256:
            raise UsageError("Keep the current implementation's affected-path set bounded; scope changes require owner judgment.", {})
        for path in head["paths"]:
            _text(path, "changed path", 4096)
            if Path(path).is_absolute() or ".." in Path(path).parts:
                raise UsageError("Bind changed paths inside the authorized repository before verification.", {})
    if not isinstance(value["blockers"], list) or len(value["blockers"]) > len(ROLES):
        raise UsageError("Retain the current blocking reports without accumulating another local history.", {})
    for captured in value["blockers"]:
        recovery.validate_receipt(captured)
    exception = value["exception"]
    if exception is not None:
        if (not isinstance(exception, dict) or set(exception) != {"code", "phase", "sources", "actions"}
                or not isinstance(exception["phase"], str) or exception["phase"] not in PHASES - {"exception", "complete"}
                or not isinstance(exception["sources"], list) or len(exception["sources"]) > 8
                or not isinstance(exception["actions"], list) or not 0 < len(exception["actions"]) <= 8):
            raise UsageError("Retain a bounded current decision packet with evidence pointers and permitted next actions.", {})
        _text(exception["code"], "exception code", 128)
        for source in exception["sources"]:
            _text(source, "exception source", 4096)
        for action in exception["actions"]:
            _text(action, "permitted recovery action", 128)
    if value["phase"] == "exception" and exception is None:
        raise UsageError("An exception stage must retain its actual unresolved decision instead of silently waiting.", {})
    if value["phase"] != "exception" and exception is not None:
        raise UsageError("Clear a decision packet only through its verified resume or reconciliation owner.", {})
    baseline = value["publication_baseline"]
    if baseline is not None and (not isinstance(baseline, str) or baseline != "unpublished" and re.fullmatch(r"\d+\.\d+\.\d+", baseline) is None):
        raise UsageError("Keep the actual pre-merge registry baseline; a guessed version cannot prove publication.", {})


def validate_job(job):
    """One current native assignment, owned here rather than mirrored into legacy rounds."""
    from . import report_delivery
    _object(job, JOB_FIELDS, "workflow native job", version=1)
    if not isinstance(job["role"], str) or job["role"] not in ROLES or job["status"] not in JOB_STATES:
        raise UsageError("Restore the current native job's supported responsibility and delivery state.", {})
    for name in ("id", "agent", "worker_kind"):
        _text(job[name], "native job " + name, 128)
    for name in ("report", "brief"):
        _absolute(job[name], "native job " + name)
    timestamp(job["at"], "Native job creation time")
    if not isinstance(job["tier"], dict) or not isinstance(job["tier"].get("model"), str):
        raise UsageError("Keep the planner-selected model and actual native launch proof on its job.", {})
    if job["pane_id"] is not None:
        _text(job["pane_id"], "native pane", 128)
    if job["native_session"] is not None and report_delivery.native_identity({"agent_session": job["native_session"]}) != job["native_session"]:
        raise UsageError("Keep the exact observed native session; a guessed or malformed identity cannot advance work.", {})
    if job["transport"] is not None and not isinstance(job["transport"], dict):
        raise UsageError("Preserve the actual native transport outcome instead of interpreting a process exit as delivery.", {})
    if job["report_evidence"] is not None:
        recovery.validate_receipt(job["report_evidence"])
    if job["claim"] is not None and not isinstance(job["claim"], dict):
        raise UsageError("Retain the owner-validated current report claim with its bound bytes.", {})


def validate_current(value, document):
    """Cross-field facts needed before any admitted current-state operation."""
    validate_progress(value)
    if len(value["jobs"].values()) != len(set(value["jobs"].values())):
        raise UsageError("Preserve one distinct canonical dispatch per current responsibility.", {})
    intent = value["pending"]
    if intent is not None:
        if intent["operation"] in ("apply", "close"):
            job = intent["job"]
            if job is None or intent["dispatches"] != [job["id"]]:
                raise UsageError("The current native effect must bind its original single job and canonical dispatch.", {})
            if intent["operation"] == "close" and (job["report_evidence"] is None or job["claim"] is None):
                raise UsageError("A native close intent requires its actual validated report bytes and claim.", {})
        elif intent["job"] is not None:
            raise UsageError("Only a native launch or close intent can hold a transient native job.", {})
    delivery = value["delivery"]
    if value["phase"] in ("publish", "cleanup", "complete") and (delivery is None or delivery["merge_commit"] is None):
        raise UsageError("Retain the actual task merge identity before publication or teardown.", {})
    if delivery is not None and (delivery["accepted"] or value["phase"] in ("cleanup", "complete")):
        channels = document["publication"]
        if (not delivery["accepted"] or delivery["merge_commit"] is None
                or channels["tessl"] is not None and not delivery["tessl_confirmed"]
                or channels["acr"] and not delivery["acr_confirmed"]):
            raise UsageError("Actual accepted delivery and each selected channel's independent confirmation precede teardown.", {})
