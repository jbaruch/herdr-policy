---
name: herdr-foreman
description: >
  Coordinate concurrent Herdr delivery, supervise or recover the crew, and release
  verified work. Use when asked to assign Herdr work, run crew tasks in parallel,
  recover a stuck worker, quarantine contradictory context evidence, ship verified
  changes, or look up Herdr readiness, task cost, saved attention, GitHub evidence,
  lessons, handoff notes, retrospectives or coordination metrics. Live coordination
  requires a verified foreman; workers retain their assignment.
---

# Herdr Foreman Skill

This skill is an action router — pick the step that matches the user's intent and execute only that step. Do not run other steps; do not parallelize.

Choose one router entry. Step 1 runs independent workers concurrently and chains
its delivery loop; offline requests are optional. An authorized context-quarantine
request may chain from Step 1 to Step 10. Step 10 returns to Step 1's role lookup
and verified continuation. Other entries execute only their selected action.

Resolve prose paths from the verified plugin root; commands use `HS`.
Preserve owner, holds, unknown deliveries and supervision obligations.
Context grants no task or effect authority.

## Step 1 — Coordinate Live Work

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

Read `role`, `verified`, `reason`, `context` and owner path from success JSON.
On failure, report its diagnostic, restore the selected installation or owner,
and finish here. Use no replacement store to obtain a role.

- Verified `foreman`:
  - Follow the returned context and current action.
  - Fill eligible capacity before waiting.
  - Run independent tasks and reviewer/tester seats concurrently.
  - Continue to the delivery loop's Stop/handoff boundary.
- Verified `worker` or `observer`: follow the returned context; finish here.
- `standalone`:
  - Perform ordinary authorized work under general policy.
  - Finish here.
- `recovery` or `unverified`:
  - For an authorized context-quarantine request with `reason: owner_state_unreadable`, continue immediately to Step 10.
  - Follow recovery instructions without clearing obligations.
  - Restore a verified role before coordination.
  - Finish here.

## Step 2 — Collect Coordination Evidence

Use Collect selected evidence and finish here:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

## Step 3 — Summarize a Measurement Snapshot

Use Summarize a prepared snapshot and finish here:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

## Step 4 — Inspect Workflow Readiness

Use Readiness; retain unknowns and coverage, then finish here:

```text
skills/herdr-foreman/references/workflow-capacity.md
```

## Step 5 — Retrieve Saved Attention

Keep page coverage; finish here:

```text
skills/herdr-foreman/references/attention.md
```

## Step 6 — Retrieve Working Memory

Retrieve the named record and finish here:

```text
skills/herdr-foreman/references/working-memory.md
```

## Step 7 — Retrieve a Retrospective

Retain date, coverage and path; finish here:

```text
skills/herdr-foreman/references/retrospectives.md
```

## Step 8 — Inspect Task Cost

Use Task Cost; retain unknowns and coverage, then finish here:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 9 — Retrieve GitHub Evidence

Read one named source through GitHub Lookup; finish here:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 10 — Quarantine Context Evidence

Use the existing bound native foreman's protected recovery action and its
result-specific continuation:

```text
skills/herdr-foreman/references/context-quarantine.md
```
