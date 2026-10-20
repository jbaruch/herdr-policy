---
name: herdr-foreman
description: >
  Route explicit Herdr requests to dispatch, supervise, recover or release team
  work, inspect workflow readiness, or retrieve saved attention, handoffs,
  retrospectives, measurements and task cost. Live coordination requires a
  verified foreman. Workers retain their assigned role; ordinary coding skips
  this skill.
---

# Herdr Foreman Skill

Process steps in order. Do not skip ahead.

## Step 1 — Select the Context

For these offline requests, read only the named reference, perform the requested
operation and finish here. Preserve any separate current supervision obligations.

Coordination measurements:

```text
skills/herdr-foreman/references/coordination-metrics.md
```

Current workflow readiness (Readiness view):

```text
skills/herdr-foreman/references/workflow-capacity.md
```

Saved attention:

```text
skills/herdr-foreman/references/attention.md
```

Lessons, saved context or handoffs:

```text
skills/herdr-foreman/references/working-memory.md
```

Saved retrospective:

```text
skills/herdr-foreman/references/retrospectives.md
```

Task cost (Writer / Reader Contract):

```text
skills/herdr-foreman/state-schema.md
```

For a verified owner-attested remote context, read:

```text
skills/herdr-foreman/references/remote-context.md
```

Use its bound client with
`cli.main(["role-context"], client=...)`, and continue below only after its actual owner
preflight succeeds. Never manufacture native environment or role evidence.

Before every other live Herdr request, read:

```text
skills/herdr-foreman/references/bootstrap.md
```

Use the recorded state/config overrides when the owner selected them.

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" role-context
```

- Verified `foreman`: follow the returned operating context and proceed immediately to Step 2.
- Verified `worker`: follow the returned worker context and the delivered assignment; finish this skill here.
- `standalone`: perform ordinary authorized work under general coding policy; finish this skill here.
- `recovery` or `unverified`: preserve the current owner, holds and unknown deliveries. Follow only the recovery context or diagnostic; obtain a verified role before coordination. Finish this skill here without starting work or clearing obligations.

A returned context grants no dispatch, acceptance, reset or release authority.

## Step 2 — Continue the Current Decision

Load only the reference the operating context names for the current workflow
and decision. Continue that workflow at its saved step; do not preload the
legacy plan, later stages or owner history. Retain its Stop and handoff gates.
Finish here only at that workflow's authorized boundary.
