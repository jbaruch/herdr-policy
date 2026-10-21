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

Process steps in order. Do not skip ahead.

Resolve prose paths from the verified plugin root; commands use `HS`.
Preserve owner, holds, unknown deliveries and supervision obligations.
Context grants no task or effect authority.

## Step 1 — Select the Request

For an explicit offline request, read only its named section, execute that
operation and finish here. These lookups are not live-work prerequisites.

| Request | Reference and section |
| --- | --- |
| Collect selected coordination evidence | `skills/herdr-foreman/references/coordination-metrics.md` — Collect selected evidence |
| Summarize a prepared measurement snapshot | `skills/herdr-foreman/references/coordination-metrics.md` — Summarize a prepared snapshot |
| Inspect workflow readiness | `skills/herdr-foreman/references/workflow-capacity.md` — Readiness |
| Retrieve saved attention | `skills/herdr-foreman/references/attention.md` — retain page coverage |
| Retrieve lessons, context or a handoff | `skills/herdr-foreman/references/working-memory.md` |
| Retrieve a retrospective | `skills/herdr-foreman/references/retrospectives.md` — retain date, coverage and path |
| Inspect task cost | `skills/herdr-foreman/references/decision-context.md` — Task Cost |
| Retrieve one named GitHub source | `skills/herdr-foreman/references/decision-context.md` — GitHub Lookup |

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

For the verified foreman, read its returned operating context and select the
current action in `skills/herdr-foreman/references/foreman-workflow.md` or its
explicitly admitted task workflow. Follow the delivery loop: fill eligible
capacity with independent authorized assignments before waiting, handle each
delivery, and address actual blockers. Run independent tasks concurrently and
reviewer/tester seats together when their shared inputs are ready.

Load the current action's named reference; reuse unchanged inputs. Routine
administration does not precede available delivery work. Preserve actual task,
ownership, hold, unknown-delivery, verification and release checks. Continue
while authorized work remains; finish only at the applicable Stop/handoff
boundary. Add no unrelated router action or whole-fleet reconstruction.
