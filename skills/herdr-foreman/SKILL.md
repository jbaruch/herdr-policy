---
name: herdr-foreman
description: >
  Coordinate concurrent Herdr delivery, supervise or recover the crew, and release
  verified work. Retrieve named readiness, cost, GitHub evidence, lessons, handoffs,
  retrospectives or coordination measurements. Live work requires a verified foreman;
  workers retain their assignment.
---

# Herdr Foreman Skill

Process steps in order. Do not skip ahead.

Resolve prose paths from the verified plugin root; commands use `HS`.
Preserve owner, holds, unknown deliveries and supervision obligations.
Context grants no task or effect authority.

## Step 1 — Select the Request

For an explicit offline request, read its named contract, execute that operation
and finish here. These lookups are not live-work prerequisites.

Coordination evidence or a prepared measurement summary:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

Workflow readiness:

```text
skills/herdr-foreman/references/workflow-capacity.md
```

Saved attention, retaining page coverage:

```text
skills/herdr-foreman/references/attention.md
```

Lessons, context or a handoff:

```text
skills/herdr-foreman/references/working-memory.md
```

Retrospective retrieval, retaining date, coverage and path:

```text
skills/herdr-foreman/references/retrospectives.md
```

Task Cost or one named source through GitHub Lookup:

```text
skills/herdr-foreman/references/decision-context.md
```

For live coordination, proceed immediately to Step 2.

## Step 2 — Verify the Live Role

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

- Verified `foreman`: proceed immediately to Step 3.
- Verified `worker`: follow its returned protocol and delivered assignment; finish this skill here.
- `standalone`: perform ordinary authorized work under general coding policy; finish this skill here.
- `recovery` or `unverified`: follow recovery instructions; restore a verified role before coordination. Finish here without clearing obligations.

Load no legacy plan, later stages or owner history.

## Step 3 — Deliver Through the Crew

Read the returned foreman context and its current action's reference. Fill
eligible capacity with independent authorized assignments before waiting;
run tasks concurrently and reviewer/tester seats together when inputs are ready.
Handle each delivery and address actual blockers. Reuse unchanged inputs.
Routine administration does not precede available delivery work.

Preserve task authority, ownership, holds, unknown deliveries and verification/
release gates. Continue while authorized work remains; finish only at the
applicable Stop/handoff boundary. Load no whole-fleet history or unrelated action.
