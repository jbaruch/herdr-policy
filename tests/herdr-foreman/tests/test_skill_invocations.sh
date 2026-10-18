#!/usr/bin/env bash
# Guard the SKILL.md conventions a consumer agent depends on.
#
# Invocation conventions, checked against EVERY skill in SKILLS below:
# 1. Every script invocation carries an explicit `bash` or `python3` interpreter. tessl packaging
#    normalizes plugin files to 0644, so a bare path is a permission-denied on
#    every consumer, and `chmod +x` in this repo does not survive publish.
#    Deterministic because the failure is invisible here: the scripts run fine
#    from a clone and break only once installed.
# 2. The `bash ` convention is present, so a rewrite that drops every
#    invocation cannot pass check 1 vacuously.
# 3. Every fenced bash block that names a plugin script (`$CP`, `skills/`, or
#    `.tessl/plugins`) opens with the resolver, then one quoted `$CP` script
#    invocation and its arguments. The plugin root differs between a
#    project-local install, a global install and a coding-policy clone, so each
#    block carries its own resolver — an agent's shell state does not survive
#    between tool calls. A repo-relative `bash skills/...` fails this check: it
#    resolves only inside a coding-policy clone (#574).
# 3b. No inline code span invokes a plugin script with arguments, so an
#    instruction cannot dodge check 3 by leaving its fence.
#
# Mode-gate conventions, checked against MODE_GATE_SKILL only:
# 4. The first step gates on HERDR_ENV before any script, and the gate turns a
#    standalone agent away by reading rather than by running a script.
# 5. Inside a Herdr round, round work reaches Step 2. Only the bounded factual
#    lookup and already-in-context residual branches finish here. Checks 4a/4b pass with the old
#    direct-execution hatch restored, so they do not cover the routing the
#    foreman actually acts on: a foreman that answers a bounded question or writes a
#    deliverable itself never dispatches the round (#470).
#
# `set -e` is dropped so every check runs and the suite reports an aggregate;
# each check captures its own status (rules/error-handling.md
# aggregate-reporting carve-out).
#
# Run: bash skills/herdr-foreman/tests/test_skill_invocations.sh
set -uo pipefail

MODE_GATE_SKILL=herdr-foreman

die() { echo "fatal: $*" >&2; exit 2; }
warn_cleanup() { echo "warn: could not remove $1" >&2; }
INSTALL_FIXTURE=""
cleanup() {
  if [[ -n "$INSTALL_FIXTURE" ]] && ! rm -rf "$INSTALL_FIXTURE"; then
    warn_cleanup "$INSTALL_FIXTURE"
  else
    INSTALL_FIXTURE=""
  fi
  return 0
}

PASS=0
FAIL=0
pass() { PASS=$((PASS+1)); }
fail() { FAIL=$((FAIL+1)); echo "  ✗ FAIL: $1" >&2; }

# Echo the first matching line number, or "" when there is no match. Exits the
# suite on a grep tool error: an unreadable SKILL.md must never read as a
# clean file. grep exits 1 on no-match and 2+ on error, and collapsing the two
# is what `|| true` would do.
first_match_line() { # <pattern> <file>
  local out rc=0
  out="$(grep -n -- "$1" "$2")" || rc=$?
  case "$rc" in
    0) printf '%s' "$out" | head -1 | cut -d: -f1 ;;
    1) printf '' ;;
    *) die "grep failed on $2 (exit ${rc}) while matching ${1}" ;;
  esac
}

check_mode_gate() { # <skill-name> <skill-file>
  local name="$1" skill="$2"

  # Checks 3 and 4 read the BODY only. Matching the whole file would find
  # HERDR_ENV in the frontmatter `description`, so deleting the entire gate
  # section would still pass -- an assertion that survives the removal of the
  # thing it asserts is not a test (rules/testing-standards.md Assertions).
  local body
  body="$(awk 'BEGIN{n=0} /^---[[:space:]]*$/{n++; next} n>=2' "$skill")" \
    || die "could not strip the frontmatter from ${skill}"
  [[ -n "$body" ]] || die "${skill} has no body after its frontmatter"

  local body_file="${TMPDIR:-/tmp}/skill-body.$$.md"
  printf '%s\n' "$body" > "$body_file" || die "could not stage the skill body"

  # 4a. The mode gate is the first step, before roster/script execution.
  local gate_line step1_line step2_line
  gate_line="$(first_match_line 'HERDR_ENV' "$body_file")"
  step1_line="$(first_match_line '^## Step 1 ' "$body_file")"
  step2_line="$(first_match_line '^## Step 2 ' "$body_file")"
  if [[ -z "$gate_line" ]]; then
    fail "${name}: the body states no HERDR_ENV gate — the frontmatter alone does not gate execution"
  elif [[ -z "$step1_line" ]]; then
    fail "${name}: could not locate the Step 1 heading in the body"
  elif [[ -z "$step2_line" ]]; then
    fail "${name}: could not locate the Step 2 heading in the body"
  elif (( step1_line < gate_line && gate_line < step2_line )); then pass
  else fail "${name}: the HERDR_ENV gate (body line ${gate_line}) is outside Step 1"; fi

  # 4b. That gate tells a standalone agent to stop, and says so before the
  # next step rather than anywhere in the file.
  local head flat
  if [[ -n "$step1_line" && -n "$step2_line" ]]; then
    head="$(sed -n "${step1_line},${step2_line}p" "$body_file")" || die "could not read the mode gate"
  else
    head=""
  fi
  flat="$(printf '%s' "$head" | tr '\n' ' ' | tr -s '[:space:]' ' ' \
    | tr '[:upper:]' '[:lower:]')" || die "could not flatten the preamble"
  if [[ "$flat" == *"this skill does not apply"* ]]; then pass
  else fail "${name}: Step 1 does not tell a non-Herdr agent the skill does not apply"; fi

  # 5. Read each Herdr-mode branch of Step 1 by its disposition, which is a
  # closed set of three literal dispositions. Inferring routing from prose is the
  # regex trap (rules/script-delegation.md): "must not proceed to Step 2"
  # reads as routing to a pattern and as its opposite to a human. The branch
  # states its disposition verbatim instead, and this check compares literals.
  local disp_proceed="Proceed to Step 2." disp_finish="Finish here."
  local disp_factual="Finish here only with no enrollment requiring supervision or a valid Stop-gate condition; otherwise resume Fleet Supervision at Step 11."
  # The residual branch's condition IS the contract, so it is pinned whole.
  # A substring would accept "not already in the foreman's context".
  local residual_label="Set, none of the above applies, and the answer is already in the foreman's context"
  local factual_label="Set, with a bounded factual lookup"
  local round_work=("lookup" "file inspection" "research" "bounded question" \
                    "review of existing code" "repository edit" "task deliverable")

  local branches
  branches="$(printf '%s\n' "$head" | awk '
    function flush(   b, label) {
      if (bullet == "") return
      b = bullet
      bullet = ""
      gsub(/[[:space:]]+/, " ", b)
      if (b !~ /^- \*\*Set[,*]/) return
      label = b
      sub(/^- \*\*/, "", label)
      sub(/\*\*.*$/, "", label)
      print label "\t" b
    }
    /^- \*\*/ { flush(); bullet = $0; next }
    /^[[:space:]]+[^[:space:]]/ { if (bullet != "") bullet = bullet " " $0; next }
    { flush() }
    END { flush() }')" || die "could not read the Step 1 branches"

  # A branch ends in one disposition or the other. The literal must open its
  # own sentence, so "Do not Proceed to Step 2." is not routing.
  local label text verdict routing_labels="" factual_text="" terminals=0 factual=0 residual=0 stray=""
  while IFS=$'\t' read -r label text; do
    [[ -n "$label" ]] || continue
    case "$text" in
      *"- ${disp_factual}") verdict=factual ;;
      *". ${disp_proceed}"|*"— ${disp_proceed}") verdict=proceed ;;
      *". ${disp_finish}"|*"— ${disp_finish}") verdict=finish ;;
      *) verdict=none ;;
    esac
    case "$verdict" in
      proceed) routing_labels+="${label}"$'\n' ;;
      finish)
        terminals=$(( terminals + 1 ))
        [[ "$label" == "$residual_label" ]] || stray="$label"
        [[ "$label" != "$residual_label" ]] || residual=$(( residual + 1 ))
        ;;
      factual)
        terminals=$(( terminals + 1 ))
        [[ "$label" == "$factual_label" ]] || stray="$label"
        factual=$(( factual + 1 ))
        factual_text="$text"
        ;;
      *) stray="$label" ;;
    esac
  done <<< "$branches"

  # 5a. Every branch disposes of its request, and only the two bounded branches end
  # the round. The old hatch was a branch that did neither.
  if [[ -n "$stray" ]]; then
    fail "${name}: Step 1 branch '${stray}' neither ends in '${disp_proceed}' nor is the residual branch ending in '${disp_finish}'"
  elif (( terminals == 2 && factual == 1 && residual == 1 )); then pass
  else fail "${name}: Step 1 has ${terminals} Herdr-mode branches ending in '${disp_finish}'; only the factual and residual branches may"; fi

  # shellcheck disable=SC2016 # Backticks are Markdown code-span delimiters matched literally, not shell substitution.
  if [[ "$factual_text" == *'Read `skills/herdr-foreman/references/team-operation.md` Bounded Factual Lookup.'* \
        && "$factual_text" == *"Answer within that boundary."* && "$factual_text" == *"Cite the source."* \
        && "$factual_text" == *"Run no round preflight, roster measurement, enrollment, report gate or context reset for the lookup."* ]]; then pass
  else fail "${name}: bounded factual lookup must bind its contract, cite facts and skip round-only overhead"; fi

  if [[ "$routing_labels" == *"Set, outside Bounded Factual Lookup, with a lookup"* \
        && "$routing_labels" == *"Set, outside Bounded Factual Lookup, with a team task or new retrospective"* ]]; then pass
  else fail "${name}: both dispatch routes must exclude the bounded factual route"; fi

  # 5b. Each kind of round work is named by a branch that routes. Dropping one
  # returns it to the foreman.
  local term missing=()
  for term in "${round_work[@]}"; do
    [[ "$routing_labels" == *"$term"* ]] || missing+=("$term")
  done
  if (( ${#missing[@]} > 0 )); then
    fail "${name}: no Step 1 branch ending in '${disp_proceed}' names: ${missing[*]}"
  else pass; fi

  rm -f "$body_file" || warn_cleanup "$body_file"
}

# The owner must refuse the original Stop violation and overlapping routing.
mode_gate_fixture_status() { # <skill-file>
  # Bash dynamic scope isolates fixture counters from the aggregate suite.
  local PASS=0 FAIL=0
  check_mode_gate "$MODE_GATE_SKILL" "$1"
  (( FAIL == 0 ))
}

check_mode_gate_regressions() { # <skill-file>
  local fixture variant rc
  fixture="$(mktemp -d)" || die "could not create mode-gate fixtures"
  INSTALL_FIXTURE="$fixture"
  if ! sed 's/^  - Finish here only.*$/  - Finish here./' "$1" > "$fixture/unconditional.md"; then
    die "could not create unconditional-finish regression"
  fi
  if ! sed 's/outside Bounded Factual Lookup, //g' "$1" > "$fixture/overlap.md"; then
    die "could not create overlapping-lookup regression"
  fi
  if ! sed 's/outside Bounded Factual Lookup, with a team task/with a team task/' "$1" > "$fixture/team-overlap.md"; then
    die "could not create overlapping-team-task regression"
  fi
  for variant in unconditional overlap team-overlap; do
    rc=0
    mode_gate_fixture_status "$fixture/$variant.md" \
      > "$fixture/$variant.log" 2>&1 || rc=$?
    case "$rc" in
      1) pass ;;
      0) fail "mode gate accepted the ${variant} regression" ;;
      *) die "mode-gate ${variant} fixture failed unexpectedly (exit ${rc})" ;;
    esac
  done
  cleanup
  [[ -z "$INSTALL_FIXTURE" ]] || die "mode-gate fixture cleanup failed; the exit trap will retry"
}

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
release = (cp / "skills/release/SKILL.md").read_text()
brief = (root / "herdr-foreman/templates/brief-release.md").read_text()
mechanics = (cp / "skills/release/SCRIPTING.md").read_text()
rules = cp / "rules"
boy_scout = (rules / "boy-scout.md").read_text()
severity = (rules / "review-severity.md").read_text()
advisory_directive = next(line for line in boy_scout.splitlines() if line.startswith("- **Advisory**"))
risk_directive = next(line for line in boy_scout.splitlines() if line.startswith("- **Unrelated blocking risk**"))
integration = (root.parent / "rules/coding-policy-integration.md").read_text()
# Generic standalone duties remain compatible with the published relocation
# oracle and the reduced package; team-specific routing belongs to Herdr.
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
rule = (root.parent / "rules/agent-team-operation.md").read_text()
import os
isolation = (Path(os.environ["HERDR_CODING_POLICY_ROOT"]) / "rules/agent-worktree-isolation.md").read_text()
integration = (root.parent / "rules/coding-policy-integration.md").read_text()
team = (root / "herdr-foreman/references/team-operation.md").read_text()
skill = (root / "herdr-foreman/SKILL.md").read_text()
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
for surface in (team, skill, common):
    assert "rules/agent-team-operation.md" in surface and "Delegation" in surface
assert "staffing" in common and "foreman" in common
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
import re
import sys
from pathlib import Path
root = Path(sys.argv[1]).parent
skill = (root / "skills/herdr-foreman/SKILL.md").read_text()
sections = re.split(r"(?=^## Step \d+ — )", skill, flags=re.M)
assert len(sections) == 18, "the resume contract needs all 17 steps"
for number, section in enumerate(sections[1:], 1):
    heading = section.splitlines()[0]
    assert heading.startswith(f"## Step {number} — "), heading
    if number == 1:
        continue
    routes = re.findall(r"```text\n(skills/herdr-foreman/references/[^\n]+\.md)\n```", section)
    assert len(routes) == 1, (number, "needs one stage contract", routes)
    target = (root / routes[0]).resolve()
    assert target.is_relative_to(root.resolve()), routes[0]
    assert target.is_file(), (number, routes[0])
    detail = target.read_text()
    assert heading in detail.splitlines(), (number, "contract lost its step", routes[0])
    assert "only the current step" in detail, routes[0]
assert len(skill.encode("utf-8")) <= 20000, "entry point exceeds the 5000-token approximation"
rule = (root / "rules/herdr-bootstrap.md").read_text()
scope = next(line for line in rule.splitlines() if line.startswith("- Applies to "))
allowed = {"skills/herdr-foreman/SKILL.md", "skills/herdr-standup/SKILL.md"}
allowed.update(str(p.relative_to(root)) for p in (root / "skills/herdr-foreman/references").glob("*.md"))
for file in (root / "skills").rglob("*.md"):
    if re.search(r"^[ \t]*HS=\.tessl/plugins/jbaruch/herdr-policy/skills/", file.read_text(), re.M):
        assert file.relative_to(root).as_posix() in allowed, (file, "bootstrap is outside its exact policy scope")
PYCONTRACT
  then pass; else fail "foreman step routes must preserve compact, shipped resume contracts"; fi
}

# Progress and failures go to stderr; stdout carries one JSON result.
run_suite() {
  local skills_root skill
  trap cleanup EXIT
  skills_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../skills" && pwd)" || die "could not resolve the skills dir"

  check_release_advisory_contract "$skills_root"
  check_probe_recovery_contract "$skills_root"
  check_delegation_contract "$skills_root"
  check_foreman_reference_routes "$skills_root"

  skill="${skills_root}/${MODE_GATE_SKILL}/SKILL.md"
  check_mode_gate "$MODE_GATE_SKILL" "$skill"
  check_mode_gate_regressions "$skill"

  echo "results: ${PASS} pass, ${FAIL} fail" >&2
  printf '{"suite":"test_skill_invocations.sh","passed":%d,"failed":%d}\n' "$PASS" "$FAIL"
  (( FAIL == 0 ))
}

# Entry-point guard (rules/file-hygiene.md Standalone Scripts).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  run_suite
fi
