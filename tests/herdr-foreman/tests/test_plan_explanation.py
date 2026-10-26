"""Batch explanations reuse real planner facts and never alter preferences."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
import io
import json
from types import SimpleNamespace
import tempfile
import unittest

from foreman import cli, plan_explanation, planner
from foreman.errors import UsageError

AT = "2026-10-21T01:42:00+00:00"
ROOT = Path(__file__).resolve().parents[3]


class PlanExplanationTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = {"measured_at": AT, "agents": {
            "codex": {"kind": "codex", "state": "idle", "headroom_pct": 66.0},
            "grok": {"kind": "grok", "state": "idle", "headroom_pct": 98.0},
            "agy": {"kind": "agy", "state": "idle", "headroom_pct": 90.0}}}
        self.plan = planner.plan(["reviewer"], self.snapshot,
            exclude={"reviewer": ["grok", "agy"]}, operator_exclude={"reviewer": ["grok"]},
            selection_rationale=["reviewer excludes agy: the fixture has no supported foreman adapter."],
            snapshot_ref={"source": "private measurement fixture", "measured_at": AT})
        self.agents = [SimpleNamespace(name=name, kind=name) for name in ("codex", "grok")]

    def test_gpt_only_batch_explains_available_excluded_and_unsupported_alternatives(self):
        original = copy.deepcopy((self.plan, self.snapshot))
        result = plan_explanation.explain(self.plan, self.agents, self.snapshot)
        rows = {row["worker_kind"]: row for row in result["providers"]["items"]}
        self.assertEqual(result["selected_providers"], ["codex"])
        self.assertEqual(rows["grok"]["observed_headroom_pct"], 98.0)
        self.assertEqual(rows["grok"]["excluded_from"], ["reviewer"])
        self.assertEqual(rows["grok"]["reason"], "excluded")
        self.assertEqual(rows["agy"]["reason"], "not_configured")
        self.assertIn("no supported foreman adapter", rows["agy"]["evidence"][0])
        self.assertTrue(result["clarification_required"])
        self.assertFalse(result["authorizes_constraint_change"])
        self.assertEqual((self.plan, self.snapshot), original)

    def test_actual_handoff_source_and_scope_survive_refresh_as_references(self):
        result = plan_explanation.explain(self.plan, self.agents, self.snapshot,
            source="Existing task handoff: operator message 2026-10-20, provider constraints", scope="session", refresh=True)
        self.assertFalse(result["clarification_required"])
        self.assertEqual(result["constraint_scope"], "session")
        self.assertEqual(result["source_verification"], "reference_only")
        self.assertEqual(result["refresh_action"], "recheck_actual_source_preserve_constraints")
        self.assertFalse(result["authorizes_dispatch"])

    def test_refresh_without_traceable_source_keeps_the_original_exclusion(self):
        result = plan_explanation.explain(self.plan, self.agents, self.snapshot, refresh=True)
        self.assertTrue(result["clarification_required"])
        self.assertIn("grok", result["clarification"])
        self.assertEqual(self.plan["assignments"], {"reviewer": "codex"})
        self.assertFalse(result["authorizes_constraint_change"])

    def test_source_snapshot_mismatch_is_not_reinterpreted_as_the_old_selection(self):
        with self.assertRaisesRegex(UsageError, "original measurement"):
            plan_explanation.explain(self.plan, self.agents, {**self.snapshot, "measured_at": "2026-10-21T02:42:00+00:00"})

    def test_pagination_and_unknown_eligibility_remain_explicit(self):
        plan = {"assignments": {"reviewer": "codex"}, "rationale": []}
        result = plan_explanation.explain(plan, self.agents, self.snapshot, limit=1)
        self.assertEqual(result["providers"]["returned"], 1)
        self.assertEqual(result["providers"]["next_offset"], 1)
        grok = plan_explanation.explain(plan, self.agents, self.snapshot)["providers"]["items"][-1]
        self.assertEqual(grok["reason"], "eligibility_unverified")

    def test_cli_availability_question_and_refresh_make_no_owner_or_config_writes(self):
        with tempfile.TemporaryDirectory(prefix="hpe-", dir="/tmp") as scratch:
            root = Path(scratch)
            config_path, snapshot_path, plan_path, handoff, owner = [root / name for name in (
                "config.json", "snapshot.json", "plan.json", "handoff.md", "owner.json")]
            configuration = json.loads((ROOT / "skills/herdr-foreman/config.example.json").read_text())
            configuration["worker_kinds"] = [row for row in configuration["worker_kinds"] if row["name"] in {"codex", "grok"}]
            configuration.pop("judge", None)
            config_path.write_text(json.dumps(configuration))
            snapshot_path.write_text(json.dumps(self.snapshot))
            plan_path.write_text(json.dumps(self.plan))
            handoff.write_text("Provider constraint: exclude Grok for this session. Source: actual fixture operator message.\n")
            before = {path: path.read_bytes() for path in (config_path, snapshot_path, plan_path, handoff)}
            for flags in ([], ["--refresh"]):
                out, err = io.StringIO(), io.StringIO()
                code = cli.main(["explain-plan", "--state", str(owner), "--config", str(config_path),
                    "--plan", str(plan_path), "--snapshot", str(snapshot_path),
                    "--constraint-source", str(handoff), "--constraint-scope", "session", *flags],
                    stdout=out, stderr=err)
                self.assertEqual(code, 0, err.getvalue())
                self.assertTrue(json.loads(out.getvalue())["diagnostic_only"])
            self.assertEqual({path: path.read_bytes() for path in before}, before)
            self.assertFalse(owner.exists())
            self.assertEqual(sorted(path.name for path in root.iterdir()), sorted(path.name for path in before))


if __name__ == "__main__":
    unittest.main()
