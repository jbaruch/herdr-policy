# Fleet Checkpoint

Read this contract when the execution plan reaches one of its steps. Execute
only the current step and the continuation it names. Step numbers refer to
`skills/herdr-foreman/SKILL.md`.

## Step 11 — Observe the Fleet

Run the bounded foreground watcher for all enrolled assignments:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" supervision-watch [--state <state-file>]
```

Retain and await its real execution handle. The JSON result gives `reason`,
`through`, and durable `events`; a quiet deadline completes only that checkpoint.

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
event IDs through the saved snapshot; schedule pending rechecks. Record no
assessed outcome and close no enrollment here.
Step 12 records acceptance after the round's gates exist. Complete due
retrospectives between checkpoints without interrupting workers. Resume the fleet
watch while any observation obligation remains; one blocked worker never hides
another worker's report. Proceed to Step 12 when the required reports are delivered
or their unavailability and recovery are recorded.
