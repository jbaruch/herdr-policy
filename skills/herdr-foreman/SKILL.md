---
name: herdr-foreman
description: >
  Assign and delegate Herdr work, supervise workers, recover interrupted
  assignments, release verified changes and inspect dispatch readiness. Retrieve
  saved follow-ups, handoffs, retrospectives, task cost and coordination
  measurements. Use when the user asks the Herdr foreman to assign an issue,
  delegate a task, supervise the crew, recover a worker, release a change,
  check ready work or retrieve those saved records. Live coordination requires
  the verified foreman; workers retain their assignment. Ordinary coding skips
  this skill.
---

# Herdr Foreman Skill

This skill is an action router — pick the step that matches the user's intent and execute only that step. Do not run other steps; do not parallelize.

Prose paths use the verified plugin root; commands use its `HS` skill directory.
Preserve the owner, holds, unknown deliveries and supervision obligations.
Each offline action reads its named reference, runs the requested operation
and finishes here. No action grants new task authority.

## Step 1 — Retrieve Coordination Measurements

Return the bounded summary or receipt:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

## Step 2 — Inspect Workflow Readiness

Use the Readiness view; retain unknowns and coverage:

```text
skills/herdr-foreman/references/workflow-capacity.md
```

## Step 3 — Retrieve Saved Attention

Read every attention page before claiming completeness:

```text
skills/herdr-foreman/references/attention.md
```

## Step 4 — Retrieve Working Memory

For lessons, saved context or handoffs:

```text
skills/herdr-foreman/references/working-memory.md
```

## Step 5 — Retrieve a Retrospective

Report the saved note's date, coverage and path:

```text
skills/herdr-foreman/references/retrospectives.md
```

## Step 6 — Inspect Task Cost

Use the Writer / Reader Contract; relay unknowns and invent no totals:

```text
skills/herdr-foreman/state-schema.md
```

## Step 7 — Coordinate Live Work

For owner-attested remote context, read:

```text
skills/herdr-foreman/references/remote-context.md
```

Use its bound client with `cli.main(["role-context"], client=...)`; the selector
owns preflight and recovery. Never manufacture role evidence.

For native live requests, read:

```text
skills/herdr-foreman/references/bootstrap.md
```

Use the current owner's selected state/config overrides when present:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" role-context
```

Success returns read-only JSON with `role`, `verified`, `reason`, `context`
and the owner path. If lookup or execution fails, report its diagnostic,
restore that installation or owner, and finish here. Select no replacement
store to obtain a role. Every returned authority field is false.

- Verified `foreman`: follow the returned operating context. Continue immediately to its workflow at the saved decision/step and load only the reference it names. Retain Stop and handoff gates; finish this skill only at that workflow's authorized boundary.
- Verified `worker`: follow its returned protocol and delivered assignment; finish this skill here.
- `standalone`: perform ordinary authorized work under general coding policy; finish this skill here.
- `recovery` or `unverified`: follow only the recovery context or diagnostic and obtain a verified role before coordination. Finish here without starting work or clearing obligations.

Do not preload the legacy plan, later stages or owner history. Role selection
grants no dispatch, acceptance, reset or release authority.
