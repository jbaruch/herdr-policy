"""Workflow declarations and worker claims cannot replace native owner evidence."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
import json
import unittest

from foreman import workflow_contract as workflow, workflow_profiles
from foreman.errors import UsageError


HEAD = "a" * 40
TASK = {"task": "fixture-task", "base_revision": "b" * 40}


def contract():
    captured = lambda name: {"path": "/private-fixture/" + name, "sha256": "c" * 64}
    risk = {"schema_version": 1, **{name: name in {"bounded_scope", "known_cause", "reversible"}
                                   for name in workflow_profiles.RISK_FIELDS}}
    return {"schema_version": 2, "task": TASK["task"], "risk": risk,
        "repository": {"github": "fixture/repository", "worktree": "/private-fixture/writer",
                       "branch": "feature/task", "base_branch": "main"},
        "config": captured("config.json"), "common": captured("common.md"),
        "briefs": {role: captured(role + ".md") for role in ("developer", "reviewer", "release")},
        "artifact_directory": "/private-fixture/current", "effects": ["write", "push", "open_pr", "merge"],
        "publication": {"tessl": None, "acr": False, "workflow": None},
        "acceptance": {"kind": "merge", "criteria": ["The authorized fixture behavior is covered."]}}


def claim(role="reviewer", outcome="verified"):
    profile = workflow.contract(contract(), TASK)
    reviewing = role in ("reviewer", "tester")
    correction = {name: name in {"scope_unchanged", "cause_settled"} for name in workflow.REVIEW_CONTEXT}
    return {"schema_version": 1, "task": TASK["task"], "head_revision": HEAD,
        "responsibilities": workflow.responsibilities(profile, role), "outcome": outcome,
        "acceptance": [{"criterion": 1, "state": "met", "evidence": "Independent fixture check."}] if reviewing else None,
        "checks": [{"responsibility": responsibility, "name": "fixture " + responsibility,
                    "result": "passed", "evidence": "Fixture assertions passed."}
                   for responsibility in workflow.responsibilities(profile, role)],
        "findings": [], "correction": correction if reviewing else None,
        "pull_request": None, "review_snapshot": None, "review_evidence": None, "publication": None}


def ready_snapshot(head, pr=123):
    """Complete public watcher envelope, used only by isolated native fixtures."""
    at = "2026-10-19T00:05:00Z"
    bodies = [{"id": 11, "state": "APPROVED", "submitted_at": at, "commit_id": head,
               "body": "Private policy fixture: no blocking findings.", "author": "policy-fixture",
               "html_url": "https://github.com/fixture/repository/pull/123#pullrequestreview-11"},
              {"id": 12, "state": "COMMENTED", "submitted_at": at, "commit_id": head,
               "body": "Private advisory fixture.", "author": "copilot-fixture",
               "html_url": "https://github.com/fixture/repository/pull/123#pullrequestreview-12"}]
    return {"pr_number": pr, "head_sha": head,
        "ci": {"status": "success", "checks": [{"bucket": "pass", "name": "private-fixture"}]},
        "reviews": {bot: {"state": row["state"], "submitted_at": at, "body": row["body"],
                           "commit_id": head, "stale": False, "requested": False}
                    for bot, row in zip(("codex", "copilot"), bodies)},
        "review_bodies": bodies, "inline_comments": {"codex": 0, "copilot": 1},
        "inline_comment_bodies": [{"id": 13, "in_reply_to_id": None, "path": "src/example.py", "line": 1,
            "body": "Private inline advice.", "author": "copilot-fixture",
            "html_url": "https://github.com/fixture/repository/pull/123#discussion_r13"}],
        "merge_state": {"status": "CLEAN", "mergeable": "MERGEABLE"},
        "watch": {"result": "ready", "attempts": 1, "elapsed_seconds": 0}}


class WorkflowContractTest(unittest.TestCase):
    def parse(self, value, role="reviewer", prefix=""):
        profile = workflow.contract(contract(), TASK)
        return workflow.claim(prefix + "WORKFLOW: " + json.dumps(value) + "\n", TASK["task"],
                              role, profile, HEAD, contract()["acceptance"]["criteria"])

    def test_bounded_profile_has_independent_combined_verification(self):
        profile = workflow.contract(contract(), TASK)
        self.assertEqual(workflow.responsibilities(profile, "reviewer"), ["review", "tests"])
        self.assertEqual(self.parse(claim(), prefix="VERDICT: approved\n")["outcome"], "verified")

    def test_complex_and_sensitive_profiles_retain_separate_responsibilities(self):
        for risk in ("cross_repository", "security_boundary", "production_effects"):
            value = contract()
            value["risk"][risk] = True
            value["briefs"]["tester"] = copy.deepcopy(value["briefs"]["reviewer"])
            profile = workflow.contract(value, TASK)
            self.assertEqual(workflow.responsibilities(profile, "reviewer"), ["review"])
            self.assertEqual(workflow.responsibilities(profile, "tester"), ["tests"])
            if risk != "cross_repository":
                self.assertTrue(profile["specialist_domains"])

    def test_missing_effects_channels_and_writer_owned_inputs_refuse_admission(self):
        cases = []
        value = contract(); value["effects"].remove("merge"); cases.append(value)
        value = contract(); value["effects"].append("publish"); cases.append(value)
        value = contract(); value["publication"]["acr"] = True; cases.append(value)
        value = contract(); value["repository"]["branch"] = "main"; cases.append(value)
        value = contract(); value["artifact_directory"] = "/private-fixture/writer/owned-by-writer"; cases.append(value)
        value = contract(); value["risk"]["known_cause"] = None; cases.append(value)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(UsageError):
                workflow.contract(value, TASK)

    def test_wrong_head_responsibility_criterion_or_failed_check_cannot_verify(self):
        cases = []
        value = claim(); value["head_revision"] = "d" * 40; cases.append(value)
        value = claim(); value["responsibilities"] = ["implementation"]; cases.append(value)
        value = claim(); value["acceptance"][0]["state"] = "unmet"; cases.append(value)
        value = claim(); value["checks"][0]["result"] = "unavailable"; cases.append(value)
        value = claim(); value["checks"] = value["checks"][:1]; cases.append(value)
        value = claim(); value["correction"]["scope_unchanged"] = None; cases.append(value)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(UsageError):
                self.parse(value, prefix="VERDICT: approved\n")

    def test_quoted_duplicate_and_conflicting_claims_do_not_advance(self):
        value = claim(); line = "WORKFLOW: " + json.dumps(value)
        profile = workflow.contract(contract(), TASK)
        for body in ("> " + line, "```json\n" + line + "\n```", "`" + line + "`", line + "\n" + line,
                     "WORKFLOW: not-json", "WORKFLOW: []"):
            with self.subTest(body=body), self.assertRaises(UsageError):
                workflow.claim(body, TASK["task"], "reviewer", profile, HEAD, ["fixture criterion"])
        with self.assertRaises(UsageError):
            self.parse(value, prefix="VERDICT: blocking\n")

    def test_blocked_release_does_not_invent_a_pull_request(self):
        value = claim("release", "blocked")
        self.assertEqual(self.parse(value, role="release")["outcome"], "blocked")
        value["outcome"] = "ready"
        with self.assertRaises(UsageError):
            self.parse(value, role="release")

    def test_current_progress_keeps_uncertain_intent_and_requires_exception_evidence(self):
        progress = workflow.initial_progress(1, "2026-10-19T00:00:00Z")
        progress["pending"] = {"schema_version": 2, "id": "fixture-intent", "operation": "apply", "argv": [],
                               "inputs": [], "effects_started": True, "dispatches": ["fixture:developer"], "job": None}
        workflow.validate_progress(progress)
        progress["phase"] = "exception"
        with self.assertRaises(UsageError):
            workflow.validate_progress(progress)
        progress["exception"] = {"id": "a" * 64, "code": "uncertain_send", "phase": "implement", "sources": [], "actions": ["native_reconciliation"]}
        workflow.validate_progress(progress)
        for field, value in (("phase", []), ("generation", True), ("round", -1)):
            bad = copy.deepcopy(progress); bad[field] = value
            with self.subTest(field=field), self.assertRaises(UsageError):
                workflow.validate_progress(bad)

    def test_release_readiness_can_report_a_source_blocker_before_a_pr_exists(self):
        value = claim("release", "blocking")
        value["correction"] = {name: name in {"scope_unchanged", "cause_settled"} for name in workflow.REVIEW_CONTEXT}
        value["findings"] = [{"schema_version": 1, "id": "readiness-defect", "severity": "blocking", "status": "open"}]
        self.assertEqual(self.parse(value, role="release")["outcome"], "blocking")
        value.update(outcome="ready", correction=None, findings=[])
        with self.assertRaisesRegex(UsageError, "PR number"):
            self.parse(value, role="release")

    def test_later_phases_need_an_implementation_and_complete_needs_settled_cleanup(self):
        progress = workflow.initial_progress(1, "2026-10-19T00:00:00Z")
        progress.update(phase="complete", head={"commit": HEAD, "tree": "b" * 40, "paths": ["src/example.py"]},
            delivery={"schema_version": 1, "pull_request": 123, "merge_commit": HEAD,
                "publisher_run": None, "tag": None, "tessl_version": None,
                "tessl_confirmed": False, "acr_confirmed": False, "accepted": True,
                "base_checkout": "/private-fixture/repository", "cleanup_step": 5})
        workflow.validate_current(progress, contract())
        for phase in ("verify", "release", "merge", "publish", "cleanup", "complete"):
            value = copy.deepcopy(progress)
            value.update(phase=phase, head=None)
            with self.subTest(phase=phase), self.assertRaisesRegex(UsageError, "implementation head"):
                workflow.validate_progress(value)
        value = copy.deepcopy(progress)
        value["delivery"]["cleanup_step"] = 4
        with self.assertRaisesRegex(UsageError, "cleanup step 5"):
            workflow.validate_progress(value)
        value = copy.deepcopy(progress)
        value["pending"] = {"schema_version": 2, "id": "unfinished", "operation": "measure", "argv": [],
                            "inputs": [], "effects_started": False, "dispatches": [], "job": None}
        with self.assertRaisesRegex(UsageError, "no remaining effect intent"):
            workflow.validate_progress(value)

    def test_scope_or_causal_uncertainty_remains_explicit_without_blocking_findings(self):
        context = {"schema_version": 1, **{field: field in {
            "scope_unchanged", "cause_settled", "authority_current", "evidence_current"}
            for field in workflow_profiles.CORRECTION_FIELDS}}
        for field in ("scope_unchanged", "cause_settled"):
            value = {**context, field: False}
            route = workflow_profiles.correction_route(value, [])
            self.assertEqual(route["action"], "decision_packet")
            self.assertFalse(route["grants_acceptance"])


if __name__ == "__main__":
    unittest.main()
