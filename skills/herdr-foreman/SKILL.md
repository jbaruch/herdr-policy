---
name: herdr-foreman
description: >
  Deliver authorized Herdr work concurrently through the crew, supervise workers,
  recover assignments and release verified changes. Inspect readiness, task cost and named GitHub evidence. Collect frozen
  coordination evidence; summarize measurement snapshots. Retrieve follow-ups,
  handoffs and retrospectives. Use when asked to assign Herdr work, supervise the
  crew, recover a worker, release a change, check ready work or retrieve task context.
  Live coordination requires the verified foreman. Workers retain their assignment;
  ordinary coding skips this skill.
---

# Herdr Foreman Skill

Choose the entry point matching the request. Live coordination follows the
delivery loop, including concurrent independent assignments through Herdr owners.
Offline retrieval steps are named requests, not prerequisites to live work.

Resolve prose paths from the verified plugin root; commands use `HS`.
Preserve owner, holds, unknown deliveries and supervision obligations.
Offline actions read their named section, return its result and finish here.
Context grants no task or effect authority.

## Step 1 — Collect Coordination Evidence

Use Collect selected evidence:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

## Step 2 — Summarize a Measurement Snapshot

Use Summarize a prepared snapshot:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

## Step 3 — Inspect Workflow Readiness

Use Readiness; retain unknowns and coverage:

```text
skills/herdr-foreman/references/workflow-capacity.md
```

## Step 4 — Retrieve Saved Attention

Read every attention page before claiming completeness:

```text
skills/herdr-foreman/references/attention.md
```

## Step 5 — Retrieve Working Memory

For lessons, saved context or handoffs:

```text
skills/herdr-foreman/references/working-memory.md
```

## Step 6 — Retrieve a Retrospective

Report the saved note's date, coverage and path:

```text
skills/herdr-foreman/references/retrospectives.md
```

## Step 7 — Inspect Task Cost

Use Task Cost; retain unknowns and page coverage:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 8 — Retrieve GitHub Evidence

Use GitHub Lookup for one named source and question:

```text
skills/herdr-foreman/references/decision-context.md
```

## Step 9 — Coordinate Live Work

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

- Verified `foreman`: continue immediately through its operating context to the saved workflow decision/step. Load its named reference. Retain Stop and handoff gates; finish at its authorized boundary.
- Verified `worker`: follow its returned protocol and delivered assignment; finish this skill here.
- `standalone`: perform ordinary authorized work under general coding policy; finish this skill here.
- `recovery` or `unverified`: follow recovery instructions; restore a verified role before coordination. Finish here without clearing obligations.

Load no legacy plan, later stages or owner history.
