"""Selected-plan authoring prevents schema repair loops without authorizing work."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
import json
import subprocess
import tempfile
import unittest
from typing import Any

from foreman import brief_inputs
from foreman.errors import UsageError


class BriefInputsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hbi-", dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.templates = self.root / "templates"
        self.templates.mkdir()
        (self.templates / "COMMON.md").write_text("{{TEAM_OPERATION}}\n{{ISSUE}}\n")
        verification = "{{REPORT}}\n{{REVIEW_BASE}} {{REVIEW_HEAD}} {{REVIEW_PACKAGE}}\n{{REPORTS_DIR}} {{SLICE_SCOPE}}\n"
        for role in ("reviewer", "tester"):
            (self.templates / ("brief-" + role + ".md")).write_text(verification)
        (self.templates / "brief-specialist.md").write_text("{{RESPONSIBILITY}}\n{{QUESTION}}\n{{REPORT}}\n{{CHECKOUT_SCOPE}}\n")
        self.policy = self.root / "worker.md"
        self.policy.write_text("Scoped worker contract\n")
        self.package = self.root / "package.diff"
        self.package.write_text("Source-bound review package fixture\n")
        self.plan = {"schema_version": 18, "assignments": {"reviewer": "review-1", "tester": "test-1", "advisor": "advise-1"},
                     "task_context": {"task": "existing-task", "fix_round": 3, "plan": "original-approach", "work": None},
                     "rounds": {"advisor": "architect"}, "requirements": {"advisor": {"specialty": "security", "required_capabilities": ["architecture"]}}}
        self.values: dict[str, Any] = {"shared": {"TEAM_OPERATION": str(self.policy), "ISSUE": "Existing authorized scope",
                                  "REVIEW_BASE": "a" * 40, "REVIEW_HEAD": "b" * 40,
                                  "REVIEW_PACKAGE": str(self.package), "QUESTION": "Assess the security boundary"}}
        self.reports = self.root / "reports"

    def prepare(self, plan=None, values=None):
        return brief_inputs.prepare(self.plan if plan is None else plan,
                                    self.values if values is None else values, self.templates, self.reports)

    def invoke(self, values=None, *, output=True):
        plan_path, values_path = self.root / "plan.json", self.root / "values.json"
        plan_path.write_text(json.dumps(self.plan))
        values_path.write_text(json.dumps(self.values if values is None else values))
        command = [sys.executable, "-I", str(brief_inputs.SKILL / "prepare-briefs.py"), "--plan", str(plan_path),
                   "--values", str(values_path), "--templates", str(self.templates), "--reports-dir", str(self.reports)]
        if output:
            command.extend(["--output", str(self.root / "round")])
        return subprocess.run(command, cwd=self.root, capture_output=True, text=True, check=False, timeout=90)

    def test_review_only_shared_fields_do_not_leak_into_the_advisor(self):
        before = copy.deepcopy((self.plan, self.values))
        values, errors, inventory = self.prepare()
        self.assertEqual(errors, [])
        self.assertEqual(values["shared"], {"TEAM_OPERATION": str(self.policy), "ISSUE": "Existing authorized scope"})
        self.assertNotIn("REVIEW_PACKAGE", values["roles"]["advisor"])
        self.assertNotIn("QUESTION", values["roles"]["reviewer"])
        self.assertEqual(values["roles"]["advisor"]["RESPONSIBILITY"], "advisor")
        self.assertEqual(inventory[-1]["round"], "architect")
        self.assertEqual(inventory[-1]["requirements"]["required_capabilities"], ["architecture"])
        self.assertEqual((self.plan, self.values), before)

    def test_selected_seat_metadata_is_derived_without_a_caller_scope_assertion(self):
        plan = {**self.plan, "assignments": {"reviewer#api": "review-api"},
                "slice_paths": {"reviewer#api": ["src/api/*"]}, "seat_digests": {"reviewer#api": "a" * 12}}
        supplied = copy.deepcopy(self.values)
        supplied["shared"].pop("QUESTION")
        values, errors, _inventory = self.prepare(plan, supplied)
        self.assertEqual(errors, [])
        self.assertEqual(values["roles"]["reviewer#api"]["SLICE_PATHS"], ["src/api/*"])
        self.assertNotIn("SLICE_SCOPE", values["roles"]["reviewer#api"])

    def test_consultation_task_and_specialty_come_from_the_selected_plan(self):
        template = self.templates / "brief-specialist.md"
        template.write_text(template.read_text() + "{{TASK}} {{SPECIALTY}}\n")
        values, errors, _inventory = self.prepare()
        self.assertEqual(errors, [])
        self.assertEqual(values["roles"]["advisor"]["TASK"], "existing-task")
        self.assertEqual(values["roles"]["advisor"]["SPECIALTY"], "security")
        supplied = copy.deepcopy(self.values)
        supplied["roles"] = {"advisor": {"TASK": "new-task", "SPECIALTY": "different"}}
        _values, errors, _inventory = self.prepare(values=supplied)
        self.assertTrue({"TASK", "SPECIALTY"} <= {row["field"] for row in errors})

    def test_matching_existing_fixed_inputs_need_no_manual_repair(self):
        supplied = copy.deepcopy(self.values)
        supplied["roles"] = {"advisor": {"RESPONSIBILITY": "advisor"}}
        values, errors, _inventory = self.prepare(values=supplied)
        self.assertEqual(errors, [])
        self.assertEqual(values["roles"]["advisor"]["RESPONSIBILITY"], "advisor")

    def test_all_missing_and_unknown_fields_are_reported_together(self):
        supplied = {"shared": {"SLICE_SCOPE": "invented", "UNKNOWN": "typo"},
                    "roles": {"reviewer": {"BAD": "typo"}, "absent": {}}}
        _values, errors, _inventory = self.prepare(values=supplied)
        fields = {row["field"] for row in errors}
        self.assertTrue({"SLICE_SCOPE", "UNKNOWN", "BAD", "REVIEW_BASE", "QUESTION", "TEAM_OPERATION"} <= fields)
        self.assertTrue({"reviewer", "tester", "advisor", "absent"} <= {row["role"] for row in errors})
        self.assertFalse((self.root / "round").exists())

    def test_foreign_task_derived_overrides_and_policy_overrides_are_refused(self):
        supplied = copy.deepcopy(self.values)
        supplied.update(task="different", roles={"advisor": {"RESPONSIBILITY": "developer", "TEAM_OPERATION": "other"}})
        _values, errors, _inventory = self.prepare(values=supplied)
        self.assertTrue({"task", "RESPONSIBILITY", "TEAM_OPERATION"} <= {row["field"] for row in errors})

    def test_null_and_other_nontext_values_do_not_become_rendered_text(self):
        supplied = copy.deepcopy(self.values)
        supplied["shared"].update(ISSUE=None, QUESTION=True)
        _values, errors, _inventory = self.prepare(values=supplied)
        self.assertTrue({"ISSUE", "QUESTION"} <= {row["field"] for row in errors})

    def test_missing_partition_metadata_and_duplicate_report_destinations_refuse(self):
        plan = {**self.plan, "assignments": {"reviewer#api": "review-api", "tester": "test-1"}}
        supplied = copy.deepcopy(self.values)
        supplied["shared"].pop("QUESTION")
        supplied["shared"]["REPORT"] = str(self.root / "same.md")
        _values, errors, _inventory = self.prepare(plan, supplied)
        self.assertTrue({"SLICE_PATHS", "SLICE_DIGEST", "REPORT"} <= {row["field"] for row in errors})

    def test_taskless_and_malformed_selected_plan_metadata_never_become_new_work(self):
        for changes in ({"task_context": None}, {"rounds": None}, {"slice_paths": []}):
            with self.subTest(changes=changes), self.assertRaises(UsageError):
                self.prepare({**self.plan, **changes})

    def test_complete_authoring_renders_once_without_native_or_owner_mutations(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        view = json.loads(result.stdout)
        self.assertTrue(view["ready"])
        self.assertFalse(view["authorizes_dispatch"])
        self.assertEqual(view["briefs"]["total"], 3)
        self.assertIn("advisor", (self.root / "round/brief-advisor.md").read_text())
        self.assertFalse(self.reports.exists())
        self.assertEqual(json.loads((self.root / "plan.json").read_text()), self.plan)

    def test_every_role_is_validated_before_any_requested_round_write(self):
        supplied = copy.deepcopy(self.values)
        supplied["roles"] = {}
        for role in self.plan["assignments"]:
            existing = self.root / (role + "-old.md")
            existing.write_text("Preserved previous report\n")
            supplied["roles"][role] = {"REPORT": str(existing)}
        result = self.invoke(supplied)
        self.assertEqual(result.returncode, 1, result.stderr)
        diagnostics = json.loads(result.stdout)["diagnostics"]
        self.assertEqual({row["role"] for row in diagnostics["items"]}, set(self.plan["assignments"]))
        self.assertTrue(all("already exists" in row["message"] for row in diagnostics["items"]))
        self.assertFalse((self.root / "round").exists())

    def test_inventory_mode_never_creates_the_requested_artifacts(self):
        result = self.invoke(output=False)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIsNone(json.loads(result.stdout)["common"])
        self.assertFalse((self.root / "round").exists())

    def test_actual_planner_rationale_notes_are_success_with_warnings(self):
        self.plan["rationale"] = ["note: excluded contributor old-worker is absent from this snapshot"]
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        view = json.loads(result.stdout)
        self.assertTrue(view["ready"])
        self.assertEqual(view["plan_notes"]["items"], self.plan["rationale"])
        self.assertEqual(view["diagnostics"]["items"], [])

    def test_historical_exclusion_note_is_explicitly_a_note_on_success(self):
        self.plan["notes"] = ["note: a historical excluded worker is absent from this snapshot"]
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        view = json.loads(result.stdout)
        self.assertTrue(view["ready"])
        self.assertEqual(view["diagnostics"]["total"], 0)
        self.assertEqual(view["plan_notes"]["items"], self.plan["notes"])


if __name__ == "__main__":
    unittest.main()
