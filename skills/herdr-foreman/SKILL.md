---
name: herdr-foreman
description: >
  Coordinate Herdr workers in parallel, recover stalled sessions, and release
  verified task changes through existing owners. Retrieve Herdr readiness,
  task costs, saved attention/memory, GitHub evidence and retrospectives.
  Use for Herdr requests: "assign work", "recover a worker", "show readiness",
  "check task cost", "find saved notes", "inspect this task's GitHub evidence",
  "run a postmortem", or "quarantine contradictory context evidence".
---

# Herdr Foreman Skill

This skill is an action router — pick the step that matches the user's intent and execute only that step. Do not run other steps; do not parallelize.

Step 1 runs concurrent workers; quarantine returns through Step 10 to Step 1.
Resolve paths from verified plugin root `HS`; preserve owners, holds, unknowns
and supervision. Context grants no authority.

## Step 1 — Coordinate Live Work

Owner-attested remote context:

```text
skills/herdr-foreman/references/remote-context.md
```

Use its bound `cli.main(["role-context"], client=...)`; never manufacture role evidence.

Native:

```text
skills/herdr-foreman/references/bootstrap.md
```

Keep the selected state/config overrides:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" role-context
```

Follow returned role/context. On failure, report why and restore that owner;
finish without replacing its store.

- Verified `foreman`:
  - Follow context.
  - Fill eligible task and verification seats concurrently.
  - Continue to Stop/handoff.
- Verified `worker` or `observer`:
  - Follow context.
  - Finish here.
- `standalone`:
  - Do authorized work under general policy.
  - Finish here.
- `recovery` or `unverified`:
  - For an authorized context-quarantine request with `reason: owner_state_unreadable`, continue immediately to Step 10.
  - Otherwise:
    - Preserve obligations.
    - Restore the verified role under recovery instructions.
    - Finish here.

## Step 2 — Collect Coordination Evidence

Return the frozen receipt and collection gaps:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

## Step 3 — Summarize a Measurement Snapshot

Return counts, deltas and limitations:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

## Step 4 — Inspect Workflow Readiness

Return readiness, capacity, unknowns and coverage:

```text
skills/herdr-foreman/references/workflow-capacity.md
```

## Step 5 — Retrieve Saved Attention

Return attention with lifecycle, sources and coverage:

```text
skills/herdr-foreman/references/attention.md
```

## Step 6 — Retrieve Working Memory

Return the named memory with evidence, freshness and gaps:

```text
skills/herdr-foreman/references/working-memory.md
```

## Step 7 — Retrieve a Retrospective

Return retrospective evidence with date, coverage and source:

```text
skills/herdr-foreman/references/retrospectives.md
```

## Step 8 — Inspect Task Cost

Return task cost facts, unmeasured fields and page coverage:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 9 — Retrieve GitHub Evidence

Return GitHub identity, state, link and coverage:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 10 — Quarantine Context Evidence

Read:

```text
skills/herdr-foreman/references/context-quarantine.md
```

Confirm original native binding, explicit authorization and eligibility before
writing. On refusal, preserve evidence and report why. After repair, return to
Step 1's verified role and saved continuation.
