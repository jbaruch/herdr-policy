"""Explain one existing batch from planner evidence without changing authority.

Source/scope come from the existing handoff or task input. They are diagnostic
references, never a new preference registry or authorization. A refresh keeps
the actual exclusions until their real source is reconciled by its owner.
"""

from . import context_output
from .errors import UsageError


SCOPES = ("task", "project", "session", "standing", "unknown")


def _facts(plan, roles):
    """Read the planner's fixed human output grammar, never report semantics."""
    rationale = plan.get("rationale", [])
    if not isinstance(rationale, list) or any(not isinstance(line, str) for line in rationale):
        raise UsageError("Restore the selected plan's recorded rationale before explaining provider eligibility.", {})
    excluded, ranked = {role: set() for role in roles}, {role: set() for role in roles}
    for role in roles:
        lines = [line for line in rationale if line.startswith(role + " -> ")]
        if len(lines) != 1:
            continue
        line = lines[0]
        if "; excluded: " in line and "; held this role " in line:
            names = line.split("; excluded: ", 1)[1].split("; held this role ", 1)[0]
            excluded[role] = set() if names == "none" else set(names.split(", "))
        if "; field was " in line and line.endswith(")"):
            field = line.split("; field was ", 1)[1][:-1]
            ranked[role] = {item.rsplit("=", 1)[0] for item in field.split(", ") if "=" in item}
    return rationale, excluded, ranked


def explain(plan, agents, snapshot, *, source=None, scope="unknown", refresh=False,
            limit=context_output.DEFAULT_LIMIT, offset=0):
    from .cli import _snapshot_headroom
    from .assign import normalize_assignments
    context_output.validate_page(limit, offset)
    if scope not in SCOPES or source is not None and (
            not isinstance(source, str) or not source.strip() or len(source.encode("utf-8")) > 1024
            or any(ord(char) < 32 for char in source)):
        raise UsageError("Supply the concise real constraint source and its task/project/session/standing scope from the existing handoff; preserve unknown provenance rather than guessing it.", {})
    assignments = normalize_assignments(plan)
    tiers = plan.get("tiers") or {}
    if not isinstance(tiers, dict):
        raise UsageError("Restore the recorded plan tiers before explaining selected models.", {})
    kinds = plan.get("worker_kinds", assignments)
    if not isinstance(kinds, dict) or set(kinds) != set(assignments) or any(not isinstance(name, str) for name in kinds.values()):
        raise UsageError("Restore this plan's actual worker kinds before explaining its selected providers.", {})
    if not isinstance(snapshot, dict):
        raise UsageError("Use the selected plan's original measurement object before explaining availability.", {})
    measured = snapshot.get("agents", {})
    if not isinstance(measured, dict):
        raise UsageError("Use the plan's actual measurement snapshot; missing availability is not an available alternative.", {})
    reference = plan.get("snapshot_ref")
    if reference is not None and not isinstance(reference, dict):
        raise UsageError("Restore the selected plan's measurement reference before explaining this batch.", {})
    expected_at = (reference or {}).get("measured_at")
    if expected_at is not None and snapshot.get("measured_at") != expected_at:
        raise UsageError("Explain the selected plan with its original measurement; a later refresh cannot rewrite why that batch was selected.", {})
    by_name = {agent.name: agent for agent in agents}
    rationale, excluded, ranked = _facts(plan, assignments)
    headroom = _snapshot_headroom(snapshot)
    rows = []
    unattributed = set()
    for name in sorted(set(by_name) | set(measured) | set(kinds.values())):
        selected = [role for role, worker in kinds.items() if worker == name]
        barred = [role for role in assignments if name in excluded[role]]
        eligible = [role for role in assignments if name in ranked[role]]
        evidence = [line for line in rationale if line.startswith(name + " was not considered for ")
                    or any(line.startswith(role + " excludes " + name + ":") for role in assignments)]
        # A named bar without an existing capability/contribution/seat reason
        # may be an operator preference. Never turn the historical string into
        # fresh authority or silently remove the constraint during refresh.
        remaining = headroom.get(name)
        if barred and not evidence and (remaining is None or remaining > 0):
            unattributed.add(name)
        agent = by_name.get(name)
        record = measured.get(name, {})
        provider = agent.kind if agent is not None else record.get("kind", "unknown") if isinstance(record, dict) else "unknown"
        if not isinstance(provider, str):
            provider = "unknown"
        reason = ("selected" if selected else "not_configured" if agent is None else
                  "excluded" if barred else "eligible_alternative" if eligible else "eligibility_unverified")
        rows.append({"worker_kind": name, "provider": provider, "selected_for": selected,
                     "selected_models": sorted({tier["model"] for role, tier in tiers.items()
                         if role in selected and isinstance(tier, dict) and isinstance(tier.get("model"), str)}),
                     "observed_headroom_pct": headroom.get(name), "excluded_from": barred,
                     "eligible_for": eligible, "reason": reason,
                     "evidence": evidence[:4], "evidence_omitted": max(0, len(evidence) - 4)})
    clarification = bool(unattributed) and (source is None or scope == "unknown")
    def build(effective):
        return {"selected_providers": sorted({row["provider"] for row in rows if row["selected_for"]}),
                "observed_at": snapshot.get("measured_at"),
                "providers": context_output.page(rows, offset, effective),
                "context_complete": offset == 0 and len(rows) <= effective,
                "constraint_source": source, "constraint_scope": scope,
                "source_verification": "reference_only",
                "clarification_required": clarification,
                "clarification": "What is the original source and scope of the carried exclusion for {}?".format(", ".join(sorted(unattributed))) if clarification else None,
                "refresh_action": "recheck_actual_source_preserve_constraints" if refresh else None,
                "diagnostic_only": True, "authorizes_constraint_change": False,
                "authorizes_dispatch": False}
    return context_output.fit_pages(build, limit, offset)


def run_command(args, state_path, config_path):
    from . import cli, config
    from .state import load_state_checked
    plan = cli._load_assignments(args.plan, document=True)
    if args.snapshot:
        snapshot = cli._read_record(args.snapshot)
    else:
        state, usable = load_state_checked(state_path, persist_migration=False)
        if not usable:
            raise UsageError("Restore readable selected owner state or supply the plan's actual --snapshot before explaining this batch.", {})
        snapshot = cli._planned_snapshot(plan, state, state_path)
        if snapshot is None:
            raise UsageError("Restore the selected plan's measurement source; supply its actual --snapshot rather than inventing provider availability.", {})
    return explain(plan, config.load_config(config_path), snapshot,
        source=args.constraint_source, scope=args.constraint_scope, refresh=args.refresh,
        limit=args.limit, offset=args.offset)


def register_commands(sub, common):
    parser = sub.add_parser("explain-plan", parents=[common])
    parser.add_argument("--plan", required=True)
    parser.add_argument("--snapshot")
    parser.add_argument("--constraint-source")
    parser.add_argument("--constraint-scope", choices=SCOPES, default="unknown")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--limit", type=int, default=context_output.DEFAULT_LIMIT)
    parser.add_argument("--offset", type=int, default=0)
