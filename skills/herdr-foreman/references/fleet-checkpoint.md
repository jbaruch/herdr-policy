# Fleet Checkpoint

Read this contract when the execution plan reaches one of its steps. Execute
only the current step and the continuation it names. Step numbers refer to
`skills/herdr-foreman/references/foreman-workflow.md`.

## Step 11 — Observe the Fleet

Run the bounded foreground watcher for all enrolled assignments:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" supervision-watch --compact [--state <state-file>]
```

Retain and await its real execution handle. The JSON result gives `reason`,
`through`, and durable `events`; a quiet deadline completes only that checkpoint.
Its event page retains pending counts and a sequence continuation. Read further
pending headers through `supervision-drain --compact`, using `--after` and the
saved `--through`. Acknowledge only handled event IDs with `supervision-ack
--compact`; earlier pending events remain explicit after a cursor advances.

Then ask which of those events need you:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" supervision-gate [--state <state-file>]
```

It returns `wake` and `suppressed`, each event with its `reason`. Acknowledge
every `suppressed` event with that reason as its outcome, without reading
anything. Only named, information-poor cases are suppressed and every other
event wakes you, including a kind the gate has never seen; which cases, and
why, is the script's decision contract — see
`skills/herdr-foreman/foreman/supervision_gate.py`, not restated here
(`rules/script-as-black-box.md`).

For each `wake` event, verify report delivery for its enrollment:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" check-member --enrollment <enrollment-id> \
  [--worktree <worker-checkout>]
```

Before checking a member, read and follow the checkpoint contract:

```text
skills/herdr-foreman/references/round-flow.md — Report Checkpoint Outcomes
```

Record user-facing obligations in the attention queue. Acknowledge only handled
event IDs through the saved snapshot; batch handled outcomes and schedule genuine
pending rechecks. Authenticated completed delivery can end that enrollment's
observation through `supervision-resolve` using its saved delivery receipt. This
does not accept its report, close its pane or satisfy any task/release gate.
Unknown or pending delivery stays enrolled. Step 12 separately assesses the
selected report. Do not wait for all reports or maintenance before taking one
task's next action. Resume the watch while observation obligations remain;
one blocked worker never hides another worker's report.
