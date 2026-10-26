"""Prepare legacy brief inputs from a selected owner plan, without dispatch.

Template fields decide where values belong. The plan owns seats, responsibilities
and slice metadata; provenance still belongs to the existing composer/provisioner.
Validate every role in private scratch space before writing the requested round.
This is an authoring adapter, not a second task or acceptance owner.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from . import context_output, composition
from .assign import normalize_assignments
from .errors import ForemanError, UsageError
from .tiers import canonical_role, require_seatable

TOKEN = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
DERIVED = frozenset({"BASE_REVISION", "BASE_PROVENANCE", "FETCHED_DEFAULT_REVISION", "CHECKOUT_SCOPE", "SLICE_SCOPE"})
POLICY = frozenset({"POLICY_INDEX", "RELEASE_SKILL", "TEAM_OPERATION"})
SKILL = Path(__file__).resolve().parents[1]


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise UsageError("Restore the readable UTF-8 JSON input before preparing briefs; no replacement plan or authority is inferred.", {"path": str(path)}) from None
    if not isinstance(value, dict):
        raise UsageError("Use a JSON object for the selected plan and brief values.", {"path": str(path)})
    return value


def fields(path):
    try:
        return set(TOKEN.findall(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError):
        raise UsageError("Restore the installed readable UTF-8 template before preparing this role.", {"path": str(path)}) from None


def prepare(plan, supplied, templates, reports_dir=None, state_path=None):
    """Return normalized values, all structural diagnostics and a field inventory."""
    assignments = normalize_assignments(plan)
    metadata = {name: plan.get(name, {}) for name in ("slice_paths", "seat_digests", "rounds", "requirements")}
    if any(not isinstance(value, dict) for value in metadata.values()):
        raise UsageError("Restore the selected plan's role metadata maps before preparing briefs; do not guess slice, round or specialist facts.", {})
    task = plan.get("task_context")
    if not isinstance(task, dict) or not isinstance(task.get("task"), str) or not task["task"]:
        raise UsageError("Save a task-bound plan with the existing plan command before preparing briefs; preserve the original task and correction count.", {})
    errors = []

    def error(role, key, message):
        errors.append({"role": role, "field": key, "message": message})

    shared = supplied.get("shared", {})
    overrides = supplied.get("roles", {})
    if not isinstance(shared, dict) or not isinstance(overrides, dict):
        raise UsageError("Brief values need shared and roles objects; use the generated field inventory instead of guessing role schemas.", {})
    for key in supplied.keys() - {"shared", "roles", "task", "state"}:
        error(None, key, "Remove the unknown top-level input; task identity comes from the selected plan.")
    if supplied.get("task", task["task"]) != task["task"]:
        error(None, "task", "Keep the selected plan's original task identity.")
    if state_path is not None and supplied.get("state", str(state_path)) != str(state_path):
        error(None, "state", "Use the same explicitly selected owner state for preparation and dispatch.")
    for role in overrides.keys() - assignments.keys():
        error(role, None, "This role is absent from the selected plan; regenerate the plan before adding a responsibility.")
    common = fields(templates / "COMMON.md")
    used = {}
    for role in assignments:
        require_seatable(role)
        if re.search(r"[/=,\x00-\x1f\x7f]", role):
            raise UsageError("Use plan role keys that can name a brief without path separators or control characters.", {"role": role})
        path = templates / ("brief-" + canonical_role(role) + ".md")
        if not path.is_file() and canonical_role(role) in composition.CONSULTATION_ROLES:
            path = templates / "brief-specialist.md"
        used[role] = fields(path)
    result = {"task": task["task"], "shared": {}, "roles": {role: {} for role in assignments}}
    selected_state = state_path if state_path is not None else supplied.get("state")
    if selected_state is not None:
        result["state"] = str(selected_state)
    for key, value in shared.items():
        if key in DERIVED or key in {"SLICE_PATHS", "SLICE_DIGEST", "RESPONSIBILITY"}:
            error(None, key, "Remove this fixed field; the owner derives it from the selected task/seat.")
        elif key in common:
            result["shared"][key] = value
        else:
            consumers = [role for role in used if key in used[role] or key in {"WORKTREE", "BRANCH"}]
            if not consumers:
                error(None, key, "No selected template uses this field; remove it or correct its name.")
            for role in consumers:
                result["roles"][role][key] = value
    if reports_dir is not None and "REPORTS_DIR" in common:
        result["shared"].setdefault("REPORTS_DIR", str(reports_dir))
    if "TASK" in common:
        if result["shared"].get("TASK", task["task"]) != task["task"]:
            error(None, "TASK", "Keep the original task identity from the selected plan.")
        result["shared"]["TASK"] = task["task"]
    plan_digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:10]
    inventory = []
    for role, required in used.items():
        values = result["roles"][role]
        own = overrides.get(role, {})
        if not isinstance(own, dict):
            error(role, None, "Use an object of semantic input values for this role.")
            own = {}
        for key, value in own.items():
            if key in {"SLICE_PATHS", "SLICE_DIGEST", "RESPONSIBILITY"}:
                expected = {"SLICE_PATHS": metadata["slice_paths"].get(role),
                            "SLICE_DIGEST": metadata["seat_digests"].get(role),
                            "RESPONSIBILITY": canonical_role(role)}[key]
                if expected is None or value != expected:
                    error(role, key, "Restore this fixed field from the selected plan; it cannot redefine the responsibility or slice.")
            elif key in DERIVED:
                error(role, key, "Remove this fixed field; use the selected plan instead of supplying derived scope.")
            elif key in POLICY:
                error(role, key, "Keep resolved policy artifact paths in shared values.")
            elif key not in required | common | {"WORKTREE", "BRANCH"}:
                error(role, key, "No template for this role uses this field; remove it or correct its name.")
            else:
                values[key] = value
        if "RESPONSIBILITY" in required:
            values["RESPONSIBILITY"] = canonical_role(role)
        requirement = metadata["requirements"].get(role, {})
        if not isinstance(requirement, dict):
            error(role, "requirements", "Restore this role's selected requirement record before preparing its brief.")
            requirement = {}
        for key, fixed in (("TASK", task["task"]), ("SPECIALTY", requirement.get("specialty"))):
            if key in required and fixed is not None:
                supplied_fixed = values.get(key, result["shared"].get(key, fixed))
                if supplied_fixed != fixed:
                    error(role, key, "Keep the original value from the selected plan instead of redefining its task or specialty.")
                values[key] = fixed
        if "SPECIALIST_CONTEXT" in required:
            values.setdefault("SPECIALIST_CONTEXT", "")
        if reports_dir is not None:
            if "REPORTS_DIR" in required and "REPORTS_DIR" not in common:
                values.setdefault("REPORTS_DIR", str(reports_dir))
            values.setdefault("REPORT", str(Path(reports_dir) / (role.replace("#", "-") + "-" + plan_digest + ".md")))
        if "#" in role:
            for key, source in (("SLICE_PATHS", "slice_paths"), ("SLICE_DIGEST", "seat_digests")):
                selected = metadata[source].get(role)
                if selected is None:
                    error(role, key, "Regenerate this seated plan with its validated partition; missing slice evidence cannot be invented.")
                else:
                    values[key] = selected
        merged = {**result["shared"], **values}
        missing = sorted(required - merged.keys() - DERIVED)
        for key in missing:
            error(role, key, "Supply the semantic input named by this installed template.")
        for key, value in merged.items():
            if key not in {"SLICE_PATHS", "SLICE_DIGEST"} and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
                error(role, key, "Supply text or a number; null, booleans and structured objects are not brief text.")
        inventory.append({"role": role, "agent": assignments[role], "fields": sorted(required - DERIVED),
                          "missing": missing, "round": metadata["rounds"].get(role),
                          "requirements": metadata["requirements"].get(role)})
    for key in sorted(common - result["shared"].keys() - DERIVED):
        error(None, key, "Supply this shared semantic input; resolved policy paths come from resolve-policy-paths.sh.")
    reports = {}
    for role, values in result["roles"].items():
        report = values.get("REPORT", result["shared"].get("REPORT"))
        if isinstance(report, str):
            if report in reports:
                error(role, "REPORT", "Choose a distinct report destination; it duplicates " + reports[report] + ".")
            reports[report] = role
    return result, errors, inventory


def compose(templates, values, output, *, run=subprocess.run):
    """Use the canonical renderer; caller values are data, never shell code."""
    with tempfile.TemporaryDirectory(prefix="herdr-brief-inputs-") as scratch:
        source = Path(scratch) / "values.json"
        source.write_text(json.dumps(values), encoding="utf-8")
        environment = {**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            result = run(["bash", str(SKILL / "compose-briefs.sh"), str(templates), str(source), str(output)],
                         capture_output=True, text=True, env=environment, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise UsageError("The canonical brief composer did not finish; preserve existing artifacts and inspect the renderer before retrying. No native assignment was sent.", {}) from None
    if result.returncode:
        return None, {"message": result.stderr[:4096], "diagnostic_truncated": len(result.stderr) > 4096}
    try:
        return json.loads(result.stdout), None
    except (ValueError, TypeError):
        raise UsageError("The canonical composer returned unreadable output; inspect its requested output directory before retrying, without dispatching.", {}) from None


def validate_roles(templates, values):
    """Independent role failures do not hide the remaining preparation checks."""
    errors = []
    with tempfile.TemporaryDirectory(prefix="herdr-brief-validation-") as scratch:
        for index, role in enumerate(values["roles"]):
            selected = {**values, "roles": {role: copy.deepcopy(values["roles"][role])}}
            _rendered, failure = compose(templates, selected, Path(scratch) / str(index))
            if failure is not None:
                errors.append({"role": role, "field": None, **failure})
    return errors


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--values")
    parser.add_argument("--templates", type=Path, default=SKILL / "templates")
    parser.add_argument("--reports-dir", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--output", type=Path, help="Write briefs only after every selected role validates.")
    parser.add_argument("--limit", type=int, default=context_output.DEFAULT_LIMIT)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        context_output.validate_page(args.limit, args.offset)
        plan = read_json(args.plan)
        values, errors, inventory = prepare(plan, read_json(args.values) if args.values else {},
                                            args.templates, args.reports_dir, args.state)
        notes = plan.get("notes", [])
        if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
            raise UsageError("Restore the selected plan's diagnostic notes before preparing briefs.", {})
        rationale = plan.get("rationale", [])
        if not isinstance(rationale, list) or any(not isinstance(line, str) for line in rationale):
            raise UsageError("Restore the selected plan's rationale before preparing its warnings and briefs.", {})
        notes = list(dict.fromkeys([*notes, *(line for line in rationale if line.startswith("note:"))]))
        if not errors:
            errors = validate_roles(args.templates, values)
        rendered = None
        def view(limit):
            artifacts = ([] if rendered is None else
                         [{"role": role, "brief": path} for role, path in rendered["briefs"].items()])
            return {"command": "prepare-briefs", "task": values["task"], "ready": not errors,
                    "writes_requested": args.output is not None,
                    "common": rendered["common"] if rendered is not None else None,
                    "briefs": context_output.page(artifacts, args.offset, limit),
                    "diagnostics": context_output.page(errors, args.offset, limit),
                    "plan_notes": context_output.page(notes, args.offset, limit),
                    "fields": context_output.page(inventory, args.offset, limit),
                    "authorizes_dispatch": False, "authorizes_acceptance": False}
        if not errors and args.output is not None:
            # Prove the complete response fits before the requested write.
            rendered = {"common": str(args.output / "COMMON.md"),
                        "briefs": {role: str(args.output / ("brief-" + role + ".md")) for role in values["roles"]}}
            context_output.fit_pages(view, args.limit, args.offset)
            rendered, failure = compose(args.templates, values, args.output)
            if failure is not None:
                errors.append({"role": None, "field": None, **failure})
        result = context_output.fit_pages(view, args.limit, args.offset)
        sys.stdout.write(context_output.printed_json(result))
        return 1 if errors else 0
    except ForemanError as exc:
        sys.stderr.write(context_output.error_text(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
