#!/usr/bin/env bash
# Verify published cross-skill contracts and current-action reference integrity.
# Native role/identity selection and installed bootstrap behavior are exercised by
# test_role_context.py and test_skill_bootstrap.py, not prose-shaped mode branches.
# stdout: one JSON suite result; stderr: failures. Exit 0 pass, 1 findings, 2 setup error.
set -uo pipefail

die() { echo "fatal: $*" >&2; exit 2; }
PASS=0
FAIL=0
pass() { PASS=$((PASS+1)); }
fail() { FAIL=$((FAIL+1)); echo "  ✗ FAIL: $1" >&2; }

# Execute a documented block's resolver and invocation against packaged-mode
# fixtures: a project-local install, a global install, a coding-policy clone
# (the current directory), and none of them. A consumer holding its own copy of
# the script, with a foreign origin or no repository at all, must refuse. Substitute a task-owned fixture
# root for the HOME token without changing the process's HOME or touching the
# user's installed plugin. The invocation runs without its documented
# arguments: placeholders like `<owner>` are redirections to a shell.
# Exercise the actual release entrypoints together: standalone has no simulated
# team artifact, and ordinary advisory replies cannot become merge predicates.
check_release_advisory_contract() {
  local skills_root="$1"
  if python3 - "$skills_root" <<'PYCONTRACT'
import sys
from pathlib import Path
root = Path(sys.argv[1])
import os
cp = Path(os.environ["HERDR_CODING_POLICY_ROOT"])
release_root = cp / "skills/release"
release = (release_root / "SKILL.md").read_text() + "\n" + "\n".join(
    path.read_text() for path in sorted((release_root / "references").glob("step-*.md")))
brief = (root / "herdr-foreman/templates/brief-release.md").read_text()
mechanics = (release_root / "references/SCRIPTING.md").read_text() + "\n" + (
    release_root / "references/release-contract.md").read_text()
rules = cp / "rules"
boy_scout = (rules / "boy-scout.md").read_text()
severity = (rules / "review-severity.md").read_text()
advisory_directive = next(line for line in boy_scout.splitlines() if line.startswith("- **Advisory**"))
risk_directive = next(line for line in boy_scout.splitlines() if line.startswith("- **Unrelated blocking risk**"))
integration = (root.parent / "skills/herdr-foreman/references/coding-policy-integration.md").read_text()
# Generic duties follow the published reduced-policy baseline; team-specific
# routing belongs to Herdr.
assert "current conversation" in risk_directive
references = {
    "herdr-foreman/references/round-completion.md": ["skills/herdr-foreman/templates/brief-release.md"],
    "herdr-foreman/references/dispatch-recovery.md": ["skills/herdr-foreman/foreman/composer.py", "skills/herdr-foreman/foreman/assign.py"],
    "herdr-foreman/references/judge-round.md": ["skills/herdr-foreman/templates/brief-judge.md", "skills/herdr-foreman/templates/brief-judge-diagnosis.md"],
    "herdr-foreman/references/round-setup.md": ["skills/herdr-foreman/references/specialists.md"],
    "herdr-foreman/state-schema.md": ["skills/herdr-foreman/provision-worktree.sh", "skills/herdr-foreman/foreman/provision.py"],
}
for source, paths in references.items():
    content = (root / source).read_text()
    for target in paths:
        assert "`" + target + "`" in content and (root.parent / target).is_file(), (source, target)
assert "reconcile --state <state-path> --dispatch <recorded-dispatch-id>" in (root / "herdr-foreman/references/dispatch-recovery.md").read_text()
assert "rules/review-severity.md" in advisory_directive
assert "task report" not in advisory_directive and "round log" not in advisory_directive
assert "Advisory findings are acknowledged in the existing task report or round log" in integration
assert "they create no follow-up or delivery prerequisite" in integration
assert "existing review conversation" in severity and "without simulating team artifacts" in severity
assert "Acknowledged — advisory noted" in release
assert "never simulate a team report" in release
assert "outside merge prerequisites" in release
assert "outside the merge predicate" in release and "outside the merge predicate" in mechanics
assert "Every inline comment must also be read" in release
assert "no follow-up issue or reference is required" in brief
assert "ruling obligations below" in brief
for content in (release, mechanics, brief, boy_scout):
    for contradiction in ("Reply on EVERY thread", "every thread has a reply",
                          "no review thread is unresolved", "existing follow-up references"):
        assert contradiction not in content, contradiction
PYCONTRACT
  then pass; else fail "release advisory routes contradict standalone/team merge contracts"; fi
}

check_probe_recovery_contract() {
  local skills_root="$1"
  if python3 - "$skills_root" <<'PYCONTRACT'
import sys
from pathlib import Path
root = Path(sys.argv[1]) / "herdr-foreman"
setup = (root / "references/round-setup.md").read_text()
recovery = (root / "references/dispatch-recovery.md").read_text()
section = setup.split("## Step 4 — Measure Headroom", 1)[1].split("## Step 5", 1)[0]
assert "Probe and startup recovery" in section
assert "measure that worker by hand" not in section
probe = recovery.split("## Probe and startup recovery", 1)[1].split("## ", 1)[0]
for obligation in ("declared provider roster", "unknown", "unavailability", "independent", "operator"):
    assert obligation in probe, obligation
assert "lifecycle.py" in probe
PYCONTRACT
  then pass; else fail "probe failures need an owner recovery route without removing providers or inventing capacity"; fi
}

check_delegation_contract() {
  local skills_root="$1"
  if python3 - "$skills_root" <<'PYCONTRACT'
import sys
from pathlib import Path
root = Path(sys.argv[1])
rule = (root.parent / "skills/herdr-foreman/references/team-scope.md").read_text()
import os
isolation = (Path(os.environ["HERDR_CODING_POLICY_ROOT"]) / "rules/agent-worktree-isolation.md").read_text()
integration = (root.parent / "skills/herdr-foreman/references/coding-policy-integration.md").read_text()
team = (root / "herdr-foreman/references/team-operation.md").read_text()
skill = (root / "herdr-foreman/references/foreman-workflow.md").read_text()
common = (root / "herdr-foreman/templates/COMMON.md").read_text()
assert "## Delegation" in rule
assert "Herdr-managed agents" in rule
for scope in ("nested", "read-only", "tools, skills or CLI wrappers"):
    assert scope in rule, scope
assert "does the task directly" in rule
assert "Team-round direct work stays within the current role's authority" in rule
assert "Standalone direct work follows every other applicable rule" in rule
assert 'Agent tool\'s `isolation: "worktree"`' not in isolation
assert "git worktree add" in isolation
assert "foreman provisions each writer's worktree" in integration
for surface in (team, skill):
    assert "skills/herdr-foreman/references/team-scope.md" in surface and "Delegation" in surface
assert "scoped worker contract" in common and "{{TEAM_OPERATION}}" in common
assert "no native" in common and "staffing" in common and "foreman" in common
assert "unavailable" in rule and "native" in rule
for name in ("reviewer", "tester", "specialist", "judge", "judge-diagnosis", "judge-weighing"):
    brief = (root / f"herdr-foreman/templates/brief-{name}.md").read_text()
    assert "do not dispatch subagents" in brief or "never dispatch a subagent" in brief, name
PYCONTRACT
  then pass; else fail "delegation guidance must use Herdr owners and preserve direct work and role restrictions"; fi
}

# Resume instructions name stable step numbers. Each routed step must reach a
# shipped, matching contract without preloading every stage of the round.
check_foreman_reference_routes() {
  local skills_root="$1"
  if python3 - "$skills_root" <<'PYCONTRACT'
import json
import re
import sys
from pathlib import Path
root = Path(sys.argv[1]).parent
router = (root / "skills/herdr-foreman/SKILL.md").read_text()
standup = (root / "skills/herdr-standup/SKILL.md").read_text()
assert len(router.encode()) <= 4096 and len(standup.encode()) <= 3072
assert 'role-context' in router and 'role-context' in standup
assert 'Verified `worker`' in router and '`standalone`' in router
assert 'recovery' in router and 'holds' in router and 'unknown' in router
skill = (root / "skills/herdr-foreman/references/foreman-workflow.md").read_text()
sections = re.split(r"(?=^## Step \d+ — )", skill, flags=re.M)
assert len(sections) == 18, "the resume contract needs all 17 steps"
for number, section in enumerate(sections[1:], 1):
    heading = section.splitlines()[0]
    assert heading.startswith(f"## Step {number} — "), heading
    routes = re.findall(r"`(skills/herdr-foreman/references/[^`]+\.md)`", section)
    assert routes, (number, "needs its current action contract")
    for route in routes:
        target = (root / route).resolve()
        assert target.is_relative_to(root.resolve()), route
        assert target.is_file(), (number, route)
assert len(skill.encode("utf-8")) <= 20000, "entry point exceeds the 5000-token approximation"
rule = (root / "skills/herdr-foreman/references/bootstrap.md").read_text()
scope = next(line for line in rule.splitlines() if line.startswith("- Applies to "))
declared = json.loads((root / '.tessl-plugin/plugin.json').read_text())["skills"]
allowed = {path + "/SKILL.md" for path in declared}
for path in declared:
    allowed.update(str(p.relative_to(root)) for p in (root / path / "references").glob("*.md"))
for file in (root / "skills").rglob("*.md"):
    if re.search(r"^[ \t]*HS=\.tessl/plugins/jbaruch/herdr-policy/skills/", file.read_text(), re.M):
        assert file.relative_to(root).as_posix() in allowed, (file, "bootstrap is outside its exact policy scope")
PYCONTRACT
  then pass; else fail "foreman step routes must preserve compact, shipped resume contracts"; fi
}

# Progress and failures go to stderr; stdout carries one JSON result.
run_suite() {
  local skills_root
  skills_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../skills" && pwd)" || die "could not resolve the skills dir"

  check_release_advisory_contract "$skills_root"
  check_probe_recovery_contract "$skills_root"
  check_delegation_contract "$skills_root"
  check_foreman_reference_routes "$skills_root"


  echo "results: ${PASS} pass, ${FAIL} fail" >&2
  printf '{"suite":"test_skill_invocations.sh","passed":%d,"failed":%d}\n' "$PASS" "$FAIL"
  (( FAIL == 0 ))
}

# Entry-point guard (rules/file-hygiene.md Standalone Scripts).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  run_suite
fi
