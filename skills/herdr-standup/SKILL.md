---
name: herdr-standup
description: >
  Collect or render a Herdr team standup, daily status table, or what each
  worker is doing. Live inspection requires the verified foreman and never
  interrupts workers. Other sessions retain their ordinary or assigned work.
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

Proceed immediately to Step 2 only for a verified `foreman`. Preserve a recovery
context, unverified role or diagnostic without roster calls, prompts or resets;
finish here. Other agents continue their ordinary or assigned work.

## Step 2 — Run the Standup

Read the workflow and execute its current step:

```text
skills/herdr-standup/references/standup-workflow.md
```
 Preserve its readiness, no-send and report-delivery gates.
Finish here after that workflow's declared result.
