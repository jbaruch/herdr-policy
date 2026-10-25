---
name: herdr-optimizer
description: >
  Optimize an assigned Herdr developer task: simplify logic, refactor duplication,
  remove dead code and redundant dependencies, and eliminate avoidable work.
  Use when a verified Herdr worker's developer brief asks it to simplify, refactor
  or clean up its named code area, or continue its assigned optimizer objective.
user-invocable: false
---

# Herdr Optimizer

Process steps in order. Do not skip ahead.

Deliver improvements through the existing developer
responsibility, worktree, verification and release owners.

## Step 1 — Establish the Assignment

Read the shared role lookup contract:

```text
skills/herdr-foreman/references/bootstrap.md
```

Use the current owner's selected state/config overrides when present:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" role-context
```

- On failure, follow its diagnostic and finish here.
- A verified worker follows the returned protocol and current developer brief.
- A verified foreman invokes `Skill(skill: "herdr-foreman")` for crew assignment
  through that router and finishes here.
- A standalone agent returns to ordinary general policy and finishes here.
- Recovery, unverified or other roles preserve their obligations and finish here.

Read `role`, `verified`, `reason` and `context` from success JSON. A verified
worker's developer assignment proceeds immediately to Step 2.

## Step 2 — Implement a Worthwhile Improvement

- Inspect the assigned area and current changes, then choose a small useful slice.
- Look for duplicated logic, dead code, unnecessary state or abstractions,
  avoidable work, redundant dependencies and simpler control flow.
- Compare expected benefit with implementation, regression and review costs.
- Preserve supported behavior and public contracts unless the brief authorizes
  a change. Prove deadness before deleting code; absence of local callers alone
  does not establish it for public interfaces or dynamic use.
- Prefer deletion or an existing mechanism over a new framework or abstraction.
- Use existing checks for behavior and targeted measurements for performance
  claims. Distinguish observed gains from expected maintenance benefits.
- Fix failed checks within scope and rerun them before delivery. Return an
  unresolved failure through the assignment's blocked-report contract.
- Keep changes reviewable. Do not combine unrelated cleanups or overlap another
  writer's work. Report a dependency or ownership conflict through the assignment.
- Choose effort appropriate to the actual task. Discovery and semantic refactoring
  are judgment work; a short diff alone does not make them mechanical.
- If no worthwhile change fits the scope and allowance, report that once and
  finish. Do not manufacture edits or repeatedly scan unchanged code.

Proceed immediately to Step 3 after the scoped change and checks are complete.

## Step 3 — Deliver the Improvement

- Deliver the implementation, behavior evidence, relevant checks and material
  limits through the current assignment's report contract.
- Use its exact report path and final marker when operating as a worker.
- Independent verification and release follow the normal task owners.
- Return the next useful candidate only when one is already known; a backlog,
  separate issue per finding and recurring status report are not required.
- A standing objective continues through the foreman's next scoped assignment.
  Never self-dispatch, extend scope, approve or merge your own work.

Finish here.
