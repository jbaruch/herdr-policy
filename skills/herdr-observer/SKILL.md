---
name: herdr-observer
description: >
  Start, recover or stop an independent Herdr factory observer; analyze its pending
  evidence, inspect collection health, and produce private weekly reports or urgent
  alerts about delivery throughput, coordination overhead, idle capacity, subscription
  balance, model/effort suitability and other improvement opportunities. Use for
  Herdr observer wake prompts, observer health checks, factory efficiency reports
  and observer alerts. Never gates delivery.
---

# Herdr Observer Skill

This skill is an action router — pick the step that matches the user's intent and execute only that step. Do not run other steps; do not parallelize.

Resolve references from the verified plugin root; commands use `HS`. Before
executing command blocks, read Installed Skill Lookup:

```text
skills/herdr-foreman/references/bootstrap.md
```

`observer.sh` exits 0 with JSON on success. Exit 2 reports refused or invalid
input or unavailable state; launcher failures also exit nonzero. Errors include
an actionable stderr diagnostic. On nonzero, finish the selected action after
reporting the diagnostic. Restore the named input, installation, native context
or private store, and inspect status before retrying that action.

## Step 1 — Start Observation

Use a dedicated named native Herdr agent. Keep its model appropriate to periodic
analysis; the observer's own effort belongs in the assessment. This role neither
occupies a delivery assignment nor runs the foreman's workflow. If provisioning
is needed, read `herdr --skill` for the installed runtime's launch contract; start collection
from that new agent. Continue delivery independently of observer availability.

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-observer/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-observer/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/observer.sh" start
```

The command verifies this native session, registers the observer and starts an
idempotent detached collector. Supply `--state /absolute/owner/state.json` for
additional owner paths absent from native discovery; repeat for distinct owners.
No worker is prompted. Read the returned status and inspect health through Step 3
immediately. Then finish the turn so this agent can sleep between wakes. Do not
add a model polling loop or keep the foreman supervising the observer.

## Step 2 — Analyze Pending Evidence

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-observer/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-observer/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/observer.sh" next
```

Success returns the saved `data.job` that caused this wake, plus a private
`draft_path` and `latest_sample_at`. Use `data.job.id` as `ID` and
`draft_path` as `DRAFT` in the commands below. Check freshness before time-sensitive
conclusions and retrieve focused newer evidence as needed.
If no job exists, finish silently. Do not reconstruct the entire
factory or replay history. For analysis and reporting follow:

```text
skills/herdr-observer/references/analysis.md
```

Use the same command lookup for the following operations on `observer.sh`:
`evidence --agent NAME` returns a bounded focused view with omissions;
`evidence --hours HOURS` accepts the `evidence_hours` values returned by `next`. Retrieve
only evidence needed for an open question. The agent makes the judgments;
candidate signals are questions, never automatic findings.

Write a warranted report only to the returned private draft, then run
`report --job ID --kind weekly --file DRAFT` for a due weekly report, or
`report --job ID --kind urgent --file DRAFT` for an earlier alert. Success returns
the private path and notification receipt. An already saved report is idempotent.
For a nonweekly analysis with nothing worth reporting, run `ack --job ID` and
finish silently. A due weekly report includes coverage gaps even when no
improvement is supported. Finish here after saving or acknowledging the job.

## Step 3 — Inspect Observer Health

Use Inspect Observer Health in the lifecycle/storage contract, then finish here:

```text
skills/herdr-observer/references/storage.md
```

## Step 4 — Stop Observation

Use Stop Observation in the same contract, then finish here:

```text
skills/herdr-observer/references/storage.md
```
