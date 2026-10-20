---
name: herdr-foreman
description: >
  Delegate Herdr tasks, supervise workers, recover assignments, release verified
  changes and inspect readiness. Retrieve follow-ups, handoffs, retrospectives,
  task cost, coordination measurements and named GitHub evidence. Use when the
  Herdr foreman is asked to assign an issue, delegate work, supervise the crew,
  recover a worker, release a change, check ready work or retrieve task context.
  Live coordination requires the verified foreman. Workers retain their
  assignment; ordinary coding skips this skill.
---

# Herdr Foreman Skill

This skill is an action router — pick the step that matches the user's intent and execute only that step. Do not run other steps; do not parallelize.

Prose paths use the verified plugin root; commands use its `HS` skill directory.
Preserve the owner, holds, unknown deliveries and supervision obligations.
Each offline action reads its named reference, runs the requested operation
and finishes here. Context grants no task or effect authority.

## Step 1 — Retrieve Coordination Measurements

Collect frozen evidence or summarize a snapshot:

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

Use the Task Cost contract; retain unknowns and page coverage:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 7 — Retrieve GitHub Evidence

Use the GitHub Lookup contract for one named source and question:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 8 — Coordinate Live Work

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
store to obtain a role.

- Verified `foreman`: follow the operating context and continue immediately to its workflow at the saved decision/step. Load only its named reference. Retain Stop and handoff gates; finish only at its authorized boundary.
- Verified `worker`: follow its returned protocol and delivered assignment; finish this skill here.
- `standalone`: perform ordinary authorized work under general coding policy; finish this skill here.
- `recovery` or `unverified`: follow recovery instructions; restore a verified role before coordination. Finish here without clearing obligations.

Do not preload the legacy plan, later stages or owner history.
