---
name: herdr-foreman
description: >
  Coordinate Herdr delivery or answer named offline Herdr lookups. Use when asked
  to assign or delegate work, recover workers, quarantine contradictory context
  evidence, release verified changes, or check readiness, task cost, attention,
  GitHub evidence, memory, retrospectives/postmortems and coordination metrics.
---

# Herdr Foreman Skill

Choose the entry that matches the request and load its selected reference.
Inspection entries are individual lookups, not a startup checklist. Step 1 owns
concurrent delivery; unselected entries add no prerequisite work.

Step 1 chains concurrent delivery. Authorized quarantine chains Step 1 to Step 10,
then returns to Step 1's role lookup and verified continuation. Other entries
execute only their selected action.

Resolve prose paths from the verified plugin root; commands use `HS`.
Preserve owner, holds, unknown deliveries and supervision obligations.
Context grants no task or effect authority.

## Step 1 — Coordinate Live Work

For owner-attested remote context, read:

```text
skills/herdr-foreman/references/remote-context.md
```

Use its bound `cli.main(["role-context"], client=...)` for preflight and recovery.
Never manufacture role evidence.

For native live requests, read:

```text
skills/herdr-foreman/references/bootstrap.md
```

Keep the selected owner's state/config overrides:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" role-context
```

Read `role`, `verified`, `reason`, `context` and owner path. On failure, report
the diagnostic, restore the selected installation or owner, and finish here.
Use no replacement store.

- Verified `foreman`: follow the returned context; fill eligible capacity and run
  independent tasks and reviewer/tester seats concurrently before waiting.
  Continue to the delivery loop's Stop/handoff boundary.
- Verified `worker` or `observer`: follow the returned context; finish here.
- `standalone`: perform ordinary authorized work under general policy; finish here.
- `recovery` or `unverified`:
  - For an authorized context-quarantine request with `reason: owner_state_unreadable`, continue immediately to Step 10.
  - Otherwise follow recovery instructions, preserve obligations, restore a verified
    role before coordination, and finish here.

## Step 2 — Collect Coordination Evidence

Return the capture receipt for the selected frozen owners and observation
window, retaining collection gaps; finish here:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

## Step 3 — Summarize a Measurement Snapshot

Return the prepared sanitized snapshot's counts, deltas and stated limitations;
finish here:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

## Step 4 — Inspect Workflow Readiness

Return the selected task's readiness reasons and eligible capacity, retaining
unknowns and page coverage; finish here:

```text
skills/herdr-foreman/references/workflow-capacity.md
```

## Step 5 — Retrieve Saved Attention

Return the named obligation or selected attention page with lifecycle, sources
and page coverage; finish here:

```text
skills/herdr-foreman/references/attention.md
```

## Step 6 — Retrieve Working Memory

Return the named capture, lesson or stow with its evidence references,
freshness and recorded gaps; finish here:

```text
skills/herdr-foreman/references/working-memory.md
```

## Step 7 — Retrieve a Retrospective

Return the selected retrospective evidence with its date, coverage and source
path; finish here:

```text
skills/herdr-foreman/references/retrospectives.md
```

## Step 8 — Inspect Task Cost

Return the selected task's effort/cost facts and unmeasured fields, retaining
page coverage; finish here:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 9 — Retrieve GitHub Evidence

Return the named GitHub source's identity, current state, source link and
evidence coverage; finish here:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 10 — Quarantine Context Evidence

Use protected quarantine and its continuation:

```text
skills/herdr-foreman/references/context-quarantine.md
```

The owner must confirm the original native binding, explicit authorization and
quarantine eligibility before its write. On refusal, preserve the evidence and
report its diagnostic. After a successful repair, return to Step 1's role lookup
and continue only under its verified role and saved continuation.
