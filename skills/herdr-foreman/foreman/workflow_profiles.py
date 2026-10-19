"""Pure outcome/verification policy for explicitly admitted background work.

This module proposes responsibilities and correction routes. It grants no
dispatch, acceptance, release or production authority. The progression owner
must derive its inputs from current owner-verified evidence and enforce native
worker independence. Legacy rounds retain their existing staffing contract.

Every input/output document is schema 1. Unknown versions or incomplete risk
facts are refused; there is no migration or optimistic default for uncertainty.
No state, clock, network or worker is read or changed here.
"""

from .errors import UsageError


SCHEMA_VERSION = 1
RISK_FIELDS = frozenset({
    "bounded_scope", "known_cause", "reversible", "production_effects",
    "data_migration", "security_boundary", "cross_repository", "unfamiliar_domain",
})
CORRECTION_FIELDS = frozenset({
    "scope_unchanged", "cause_settled", "authority_current", "evidence_current",
    "contradictory_evidence", "repeated_defect", "non_converged",
    "changed_production_plan",
})


def _document(value, fields, label):
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value["schema_version"] != SCHEMA_VERSION or set(value) != fields | {"schema_version"}):
        raise UsageError(
            "Supply the complete supported schema-1 {}; retrieve missing owner evidence instead of assuming defaults.".format(label), {})


def _facts(value, fields, label):
    _document(value, fields, label)
    if any(type(value[key]) is not bool for key in fields):
        raise UsageError(
            "Resolve unknown {} facts through a bounded decision before selecting a workflow.".format(label), {})


def select_profile(risk):
    """Describe the required responsibilities without staffing or admitting work.

    A combined verifier supplies both review and test evidence independently
    of implementation. Separate seats remain mandatory for complex/sensitive
    work. Role labels alone never prove distinct native worker identities.
    """
    _facts(risk, RISK_FIELDS, "risk")
    sensitive = any(risk[key] for key in ("production_effects", "data_migration", "security_boundary"))
    complex_work = (not all(risk[key] for key in ("bounded_scope", "known_cause", "reversible"))
                    or any(risk[key] for key in ("cross_repository", "unfamiliar_domain")))
    profile = "sensitive" if sensitive else "complex" if complex_work else "bounded"
    verifiers = ([{"responsibility": "verifier", "evidence": ["review", "tests"],
                   "independent_from": ["outcome_owner"]}] if profile == "bounded" else [
                       {"responsibility": "reviewer", "evidence": ["review"],
                        "independent_from": ["outcome_owner", "tester"]},
                       {"responsibility": "tester", "evidence": ["tests"],
                        "independent_from": ["outcome_owner", "reviewer"]}])
    specialists = []
    for field, domain in (("security_boundary", "security"), ("data_migration", "persisted_data"),
                          ("production_effects", "production_recovery"), ("unfamiliar_domain", "affected_domain")):
        if risk[field]:
            specialists.append(domain)
    return {
        "schema_version": 1,
        "profile": profile,
        "outcome_owner": ["implementation", "correction", "verification_coordination", "release_coordination"],
        "verification": verifiers,
        "specialist_domains": specialists,
        "acceptance_authority": "admitted_task_owner_contract",
        "progression_authority": "verified_single_owner_generation",
        "release_contract": "coding_policy_unchanged",
        "production_gate_required": risk["production_effects"] or risk["data_migration"],
        "activation": "requires_explicit_admission_and_authority_handoff",
    }


def correction_route(context, findings):
    """Choose a task-local route from already assessed, artifact-bound findings.

    This does not parse report prose or determine whether a finding was fixed.
    An advisory never creates another correction/review round. An unresolved
    uncertainty never becomes approval. No round count enables self-approval.
    """
    _facts(context, CORRECTION_FIELDS, "correction context")
    if not isinstance(findings, list):
        raise UsageError("Supply the current owner's structured finding list before routing a correction.", {})
    seen = set()
    for item in findings:
        _document(item, {"id", "severity", "status"}, "finding")
        identifier = item["id"]
        if (not isinstance(identifier, str) or not identifier.strip()
                or len(identifier.encode("utf-8")) > 256 or any(ord(char) < 32 for char in identifier)
                or identifier in seen or item["severity"] not in ("blocking", "advisory", "uncertain")
                or item["status"] not in ("open", "resolved", "disputed")):
            raise UsageError("Restore unique finding identities and supported severity/status values from the current assessment.", {})
        seen.add(identifier)
    current = [item for item in findings if item["status"] != "resolved"]
    blocking = [item["id"] for item in current if item["severity"] == "blocking"]
    advisories = [item["id"] for item in current if item["severity"] == "advisory"]
    reasons = []
    if not context["authority_current"]:
        reasons.append("authority_handoff_required")
    if not context["evidence_current"]:
        reasons.append("retrieve_current_bound_evidence")
    for field in ("contradictory_evidence", "repeated_defect", "non_converged", "changed_production_plan"):
        if context[field]:
            reasons.append(field)
    if any(item["severity"] == "uncertain" for item in current):
        reasons.append("unresolved_evidence")
    if any(item["status"] == "disputed" and item["severity"] != "advisory" for item in current):
        reasons.append("disputed_blocking_finding")
    if blocking:
        if not context["scope_unchanged"]:
            reasons.append("scope_changed")
        if not context["cause_settled"]:
            reasons.append("causal_uncertainty")
    action = "decision_packet" if reasons else "owner_correction" if blocking else "continue_required_verification_or_release"
    return {"schema_version": 1, "action": action, "scope": "task",
            "blocking_findings": blocking, "acknowledge_advisories": advisories,
            "reasons": reasons, "grants_acceptance": False, "grants_release": False}
