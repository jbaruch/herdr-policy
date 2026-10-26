"""Real packaged authoring/provision/apply handoff using owned local Git.

Only native agent transport is fake. The current planner, shipped templates,
complete pre-write validation, composer, provision receipts and live apply
owners run without hand-editing intermediate values or plans.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from foreman import brief_inputs, cli, recovery, supervision
from foreman.state import empty_state, save_state
from tests import test_cli as fixtures

SKILL = brief_inputs.SKILL
AT = "2026-10-25T01:00:00+00:00"


class PackagedBriefInputsTest(unittest.TestCase):
    def test_developer_to_review_test_security_renders_and_applies_without_repairs(self):
        with tempfile.TemporaryDirectory(prefix="hpi-", dir="/tmp") as scratch:
            root = Path(scratch).resolve()
            environment = {**os.environ, "WORKTREE_ROOT": str(root / "worktrees"),
                "XDG_STATE_HOME": str(root / "state-home"), "XDG_CONFIG_HOME": str(root / "config-home"),
                "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
            def run(arguments, *, cwd=root):
                return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True,
                                      text=True, check=True, timeout=60)
            origin, shared, writer = root / "origin.git", root / "shared", root / "worktrees/task"
            run(["git", "init", "--bare", "--initial-branch=main", str(origin)])
            run(["git", "clone", str(origin), str(shared)])
            (shared / "src").mkdir()
            (shared / "src/parser.py").write_text("value = 0\n")
            run(["git", "add", "."], cwd=shared)
            run(["git", "commit", "-m", "Private fixture base"], cwd=shared)
            run(["git", "push", "origin", "main"], cwd=shared)
            provision = json.loads(run(["bash", str(SKILL / "provision-worktree.sh"), str(shared),
                                        "feat/authoring", str(writer)]).stdout)
            state_path, config_path = root / "owner.json", root / "config.json"
            state = empty_state()
            recovery.register_task(state["recovery"], {"task": "original-task", "base_revision": provision["base_revision"],
                "scope": "Correct the fixture parser", "allowed_paths": ["src/*"],
                "authorization": {"source": "Owned protocol fixture", "quote": "Implement and independently verify this parser correction."}}, AT)
            save_state(state_path, state)
            configuration = json.loads((SKILL / "config.example.json").read_text())
            configuration["worker_kinds"] = [worker for worker in configuration["worker_kinds"] if worker["name"] == "codex"]
            configuration["worker_kinds"][0]["capabilities"] = ["architecture"]
            configuration.pop("judge", None)
            config_path.write_text(json.dumps(configuration))
            snapshot = root / "snapshot.json"
            snapshot.write_text(json.dumps({"schema_version": 6, "measured_at": AT, "agents": {
                "codex": {"kind": "codex", "state": "idle", "headroom_pct": 95.0}}, "failed_agents": [], "skipped_agents": []}))
            native = fixtures.FreshOwnerNative()
            native.frames = [native.EMPTY]
            supervision.bind(state_path, supervision.identity("fixture-lead", str(root), "fixture", pane_id="lead-pane"),
                             AT, root=root / "bindings")
            policy = root / "policy.md"
            policy.write_text("Owned deterministic policy fixture; no external runtime authority.\n")
            reports = root / "reports"
            reports.mkdir()
            supplied = {"shared": {"SHARED_CHECKOUT": str(shared), "AUTHORITY_STATEMENT": "Owned isolated fixture",
                "TASK_AUTHORIZATION": "Owned protocol fixture: implement and verify the parser correction",
                "AUTHORIZED_ACTIONS": "Write source in the named fixture and reports", "EXTERNAL_PERMISSION": "none",
                "POLICY_INDEX": str(policy), "RELEASE_SKILL": str(policy), "TEAM_OPERATION": str(SKILL / "references/worker-context.md"),
                "GATES": "- Independent fixture parser check", "WORKTREE": str(writer), "BRANCH": "feat/authoring",
                "ISSUE": "Correct the fixture parser", "SPECIALIST_CONTEXT": "No unrelated scope"}}
            base = ["--state", str(state_path), "--config", str(config_path)]
            def invoke(arguments):
                out, err = io.StringIO(), io.StringIO()
                code = cli.main(base + arguments, client=native, stdout=out, stderr=err)
                self.assertEqual(code, 0, err.getvalue())
                return json.loads(out.getvalue())
            def handoff(roles, supplied_values, *, extra=()):
                plan = invoke(["plan", "--roles", ",".join(roles), "--task", "original-task", "--snapshot", str(snapshot), "--now", AT, *extra])
                values, errors, _inventory = brief_inputs.prepare(plan, supplied_values, SKILL / "templates", reports, state_path)
                self.assertEqual(errors, [])
                self.assertEqual(brief_inputs.validate_roles(SKILL / "templates", values), [])
                composed, failure = brief_inputs.compose(SKILL / "templates", values, root / ("round-" + roles[0]))
                self.assertIsNone(failure)
                assert composed is not None
                plan_path = root / (roles[0] + "-plan.json")
                plan_path.write_text(json.dumps(plan))
                argv = ["apply", "--assignments", str(plan_path), "--task", "original-task", "--now", AT,
                        "--common", composed["common"], "--composer-settle", "0"]
                for role, path in composed["briefs"].items():
                    argv += ["--brief", role + "=" + path, "--report", role + "=" + values["roles"][role]["REPORT"]]
                result = invoke(argv)
                self.assertTrue(all(row["status"] == "applied" for row in result["applied"]))
                return plan, composed, values
            real_spawn, real_apply = cli.lifecycle.spawn, cli.apply_assignments
            with patch.dict(os.environ, environment), patch("foreman.cli.retrospective_runtime.Guard"), \
                    patch("foreman.cli.lifecycle.spawn", side_effect=lambda *a, **kw: real_spawn(*a, **kw, sleep=lambda _: None)), \
                    patch("foreman.cli.apply_assignments", side_effect=lambda *a, **kw: real_apply(*a, **kw, sleep=lambda _: None)):
                developer, _composed, values = handoff(["developer"], supplied)
                Path(values["roles"]["developer"]["REPORT"]).write_text("Private source delivery; independent checks pending.\n")
                (writer / "src/parser.py").write_text("value = 1\n")
                run(["git", "commit", "-am", "Private parser correction"], cwd=writer)
                run(["git", "push", "origin", "feat/authoring"], cwd=writer)
                head = run(["git", "rev-parse", "HEAD"], cwd=writer).stdout.strip()
                package = root / "review.diff"
                run(["bash", str(SKILL / "review-package.sh"), provision["base_revision"], head, str(package)], cwd=writer)
                supplied["shared"].update(REVIEW_BASE=provision["base_revision"], REVIEW_HEAD=head,
                    REVIEW_PACKAGE=str(package), OBJECTIVE="Assess the existing parser security boundary",
                    ACCEPTANCE_CRITERIA="CRITERION 1: explain the source boundary and any blocking defect",
                    SCOPE_LIMITS="Read the assigned checkout and report; preserve the implementation scope",
                    INPUTS=str(package), TOOLS_AND_SKILLS="Read the supplied source and package",
                    KNOWLEDGE="Owned fixture parser", CONTRIBUTION_HISTORY="No prior contribution by the selected fresh identities")
                requirements = root / "requirements.json"
                requirements.write_text(json.dumps({"schema_version": 1, "assignments": {"advisor": {
                    "specialty": "security", "required_capabilities": ["architecture"], "independent": True,
                    "engagement": "parser-security"}}}))
                context = root / "round-context.json"
                context.write_text(json.dumps({"advisor": {"security_trigger": True}}))
                plan, composed, normalized = handoff(["reviewer", "tester", "advisor"], supplied,
                    extra=["--requirements", str(requirements), "--round-context", str(context)])
                self.assertEqual(plan["tiers"]["advisor"]["round"], "architect")
                self.assertNotIn("REPORTS_DIR", normalized["roles"]["advisor"])
                self.assertNotIn("REVIEW_PACKAGE", normalized["roles"]["advisor"])
                self.assertIn("CRITERION 1:", Path(composed["briefs"]["advisor"]).read_text())
                self.assertTrue(set(developer["assignments"].values()).isdisjoint(plan["assignments"].values()))
                self.assertEqual(len([event for event in native.events if event[0] == "prompt"]), 4)
                self.assertEqual(len(supervision.load(state_path)["members"]), 4)


if __name__ == "__main__":
    unittest.main()
