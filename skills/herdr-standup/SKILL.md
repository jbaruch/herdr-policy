---
name: herdr-standup
description: >
  Collect Herdr standup evidence, check worker readiness, account for missing
  reports, render a daily status table and relay blockers without interrupting
  workers. Use when the user asks for a Herdr standup, team status update,
  daily check-in, worker progress report or what each worker is doing. Live
  inspection requires the verified foreman; ordinary work skips this skill.
---

# Herdr Standup Skill

Process steps in order. Do not skip ahead.

## Step 1 — Verify the Foreman

Before this command, read:

```text
skills/herdr-foreman/references/bootstrap.md
```
Use the recorded state/config overrides when the owner selected them.

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" role-context
```

Proceed immediately to Step 2 only for a verified `foreman`. For `recovery`,
`unverified` or a nonzero exit, report the returned reason and follow its
restoration diagnostic; preserve holds and unknown deliveries, then finish here
without roster calls, prompts or resets. Workers and standalone agents continue
their assigned or ordinary work and finish this skill here.

## Step 2 — Run the Standup

Read the workflow and execute its current step:

```text
skills/herdr-standup/references/standup-workflow.md
```
 Preserve its readiness, no-send and report-delivery gates.
Retain unknown rows for missing evidence. Report an atomic-readiness refusal
without prompting a worker. Render the table and relay its blockers through
that workflow's existing gates. Finish here after its declared result.
