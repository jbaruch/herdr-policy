"""Staffing and correction decisions preserve verification and task isolation."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "herdr-foreman"))
from foreman.errors import UsageError
from foreman.workflow_profiles import correction_route, select_profile


def risk(**changes):
    return {"schema_version": 1, "bounded_scope": True, "known_cause": True,
            "reversible": True, "production_effects": False, "data_migration": False,
            "security_boundary": False, "cross_repository": False,
            "unfamiliar_domain": False, **changes}


def context(**changes):
    return {"schema_version": 1, "scope_unchanged": True, "cause_settled": True,
            "authority_current": True, "evidence_current": True,
            "contradictory_evidence": False, "repeated_defect": False,
            "non_converged": False, "changed_production_plan": False, **changes}


def finding(identifier="finding-1", severity="blocking", status="open"):
    return {"schema_version": 1, "id": identifier, "severity": severity, "status": status}


class WorkflowProfilesTest(unittest.TestCase):
    def test_small_change_combines_review_and_testing_with_independence(self):
        proposal = select_profile(risk())
        self.assertEqual(proposal["profile"], "bounded")
        self.assertEqual(proposal["verification"], [{"responsibility": "verifier", "evidence": ["review", "tests"],
                                                   "independent_from": ["outcome_owner"]}])
        self.assertEqual(proposal["activation"], "requires_explicit_admission_and_authority_handoff")
        self.assertEqual(proposal["release_contract"], "coding_policy_unchanged")

    def test_uncertain_or_complex_work_keeps_separate_independent_checks(self):
        for change in ({"bounded_scope": False}, {"known_cause": False}, {"reversible": False},
                       {"cross_repository": True}, {"unfamiliar_domain": True}):
            with self.subTest(change=change):
                proposal = select_profile(risk(**change))
                self.assertEqual(proposal["profile"], "complex")
                self.assertEqual([row["evidence"] for row in proposal["verification"]], [["review"], ["tests"]])
                self.assertIn("tester", proposal["verification"][0]["independent_from"])
                self.assertIn("reviewer", proposal["verification"][1]["independent_from"])

    def test_sensitive_changes_require_relevant_specialists_and_effect_gate(self):
        for field, domain in (("security_boundary", "security"), ("data_migration", "persisted_data"),
                              ("production_effects", "production_recovery")):
            with self.subTest(field=field):
                proposal = select_profile(risk(**{field: True}))
                self.assertEqual(proposal["profile"], "sensitive")
                self.assertIn(domain, proposal["specialist_domains"])
                self.assertEqual(len(proposal["verification"]), 2)
                self.assertEqual(proposal["production_gate_required"], field != "security_boundary")

    def test_missing_unknown_or_future_risk_never_selects_an_optimistic_default(self):
        missing = risk()
        del missing["production_effects"]
        for value in (missing, risk(known_cause=None), risk(known_cause="true"), risk(known_cause=1),
                      risk(schema_version=2), risk(schema_version=True), {**risk(), "new_field": False}):
            with self.subTest(value=value):
                with self.assertRaises(UsageError):
                    select_profile(value)

    def test_settled_blocking_correction_stays_with_outcome_owner(self):
        proposal = correction_route(context(), [finding(), finding("advice", "advisory")])
        self.assertEqual(proposal["action"], "owner_correction")
        self.assertEqual(proposal["blocking_findings"], ["finding-1"])
        self.assertEqual(proposal["acknowledge_advisories"], ["advice"])
        self.assertEqual(proposal["scope"], "task")
        self.assertFalse(proposal["grants_acceptance"])

    def test_advisory_only_feedback_never_creates_a_repair_round(self):
        proposal = correction_route(context(), [finding("advice", "advisory", "disputed"),
                                               finding("old", "blocking", "resolved")])
        self.assertEqual(proposal["action"], "continue_required_verification_or_release")
        self.assertEqual(proposal["blocking_findings"], [])
        self.assertEqual(proposal["acknowledge_advisories"], ["advice"])
        self.assertFalse(proposal["grants_release"])

    def test_nonconvergence_scope_changes_and_uncertainty_escalate_task_only(self):
        cases = [({"scope_unchanged": False}, "scope_changed"), ({"cause_settled": False}, "causal_uncertainty"),
                 ({"repeated_defect": True}, "repeated_defect"), ({"non_converged": True}, "non_converged"),
                 ({"contradictory_evidence": True}, "contradictory_evidence"),
                 ({"changed_production_plan": True}, "changed_production_plan"),
                 ({"authority_current": False}, "authority_handoff_required"),
                 ({"evidence_current": False}, "retrieve_current_bound_evidence")]
        for changes, reason in cases:
            with self.subTest(changes=changes):
                proposal = correction_route(context(**changes), [finding()])
                self.assertEqual(proposal["action"], "decision_packet")
                self.assertIn(reason, proposal["reasons"])
                self.assertEqual(proposal["scope"], "task")

    def test_disputed_or_unclassified_material_evidence_never_becomes_approval(self):
        for item, reason in ((finding(status="disputed"), "disputed_blocking_finding"),
                             (finding(severity="uncertain"), "unresolved_evidence")):
            with self.subTest(item=item):
                proposal = correction_route(context(), [item])
                self.assertEqual(proposal["action"], "decision_packet")
                self.assertIn(reason, proposal["reasons"])
                self.assertFalse(proposal["grants_acceptance"])

    def test_malformed_findings_and_unresolved_context_are_refused(self):
        for items in (None, {}, [finding(), finding()], [finding(status="approved")],
                      [finding(severity="unknown")], [finding(identifier="bad\nidentity")],
                      [{**finding(), "schema_version": 2}], [{**finding(), "unbound": True}]):
            with self.subTest(items=items):
                with self.assertRaises(UsageError):
                    correction_route(context(), items)
        with self.assertRaises(UsageError):
            correction_route(context(evidence_current=None), [])

    def test_proposals_leave_caller_evidence_intact_and_do_not_share_mutable_output(self):
        source_risk, source_context, findings = risk(), context(), [finding()]
        original = copy.deepcopy((source_risk, source_context, findings))
        proposal = select_profile(source_risk)
        correction_route(source_context, findings)
        proposal["verification"][0]["evidence"].clear()
        self.assertEqual((source_risk, source_context, findings), original)
        self.assertEqual(select_profile(source_risk)["verification"][0]["evidence"], ["review", "tests"])


if __name__ == "__main__":
    unittest.main()
