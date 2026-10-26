---
name: herdr-foreman
description: >
  Use when asked to coordinate/delegate Herdr work, recover workers, quarantine
  contradictory context evidence, release changes, or inspect readiness, costs,
  attention, GitHub, memory, retrospectives/postmortems and coordination metrics.
---

# Herdr Foreman Skill

This skill is an action router — pick the step that matches the user's intent and execute only that step. Do not run other steps; do not parallelize.

Step 1 delivers concurrent work; authorized quarantine chains Step 1 → Step 10 →
Step 1's verified role. Others finish after their selected action.
Resolve paths from the verified plugin root (`HS`). Preserve owners, holds,
unknown deliveries and supervision. Context grants no authority.

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

Read the returned role, verification, reason, context and owner path. On failure,
report the diagnostic, restore that owner and finish; use no replacement store.

- Verified `foreman`: follow context; fill independent task/reviewer/tester
  capacity concurrently and continue to Stop/handoff.
- Verified `worker` or `observer`: follow the returned context; finish here.
- `standalone`: perform ordinary authorized work under general policy; finish here.
- `recovery` or `unverified`:
  - For an authorized context-quarantine request with `reason: owner_state_unreadable`, continue immediately to Step 10.
  - Otherwise preserve obligations, restore the verified role under recovery
    instructions, and finish here.

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

Return task readiness, eligible capacity, unknowns and page coverage:

```text
skills/herdr-foreman/references/workflow-capacity.md
```

## Step 5 — Retrieve Saved Attention

Return the named obligation or attention page with lifecycle, sources and coverage:

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

Return GitHub identity, state, source link and evidence coverage:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 10 — Quarantine Context Evidence

Read:

```text
skills/herdr-foreman/references/context-quarantine.md
```

Before writing, the owner confirms original native binding, explicit authorization
and quarantine eligibility. Preserve refused evidence and report its diagnostic.
After repair, return to Step 1's verified role and saved continuation.
