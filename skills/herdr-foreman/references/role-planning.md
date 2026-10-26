# Role Planning

Read this contract when the execution plan reaches one of its steps. Execute
only the current step and the continuation it names. Step numbers refer to
`skills/herdr-foreman/references/foreman-workflow.md`.

## Step 5 — Plan the Roles

Read the open tasks waiting for a seat, oldest first:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" foreman-queue
```

It returns a byte-bounded CLI view with `schema_version: 2`, `queue`,
`pagination`, `context_complete`, `authorizes_progression: false` and the output
budget. The page metadata contains `total`, `offset`, `limit`, `returned`,
`omitted` and `next_offset`. Continue with `--offset <next_offset>` and the same
owner flags when the selected question needs another page; `--limit N` requests
a row bound that may shrink to fit the printed-byte budget. Follow returned
offsets until `next_offset` is null before claiming to have inspected the full
queue. A partial page never proves that no authorized work remains. Select only
from inspected entries and verify that task's current owner gates before acting;
unexamined entries remain pending, rather than becoming a mandatory global
context reload for an individual task decision. Each entry names `task`,
`waiting_for` (a list of `developer`, `reviewer` or `tester`),
`dispatched_seats`, `since`, `developer` and `fix_round`. A non-zero exit names
an unusable state file on stderr; restore it before planning. Tasks with an
active worker are omitted. A partitioned verifier stays listed with its
dispatched slices; check them against the validated partition. The order is a
default; choose another when the round needs it.

Choose the responsibilities needed next under `skills/herdr-foreman/references/specialists.md`.
Supply its requirements file for specialized work. Schedule consultation and
verification as the task needs them. `plan` bars a developer reserved to
another task and a worker with an active enrollment, and names each bar in its
`rationale`; do not pass `--exclude` for either. `apply` re-reads the
reservations before sending. Reusing a reserved developer elsewhere requires
closing its task first.

The composition triggers decide part of that roster. Classify this round
against the repo's declaration first. For a pre-implementation round, pass
`--planned` naming the surfaces the work will touch. A round that writes no
repository content — an investigation, an architecture or advisory consultation
— declares `writes_repository: false` in that file instead
(`skills/herdr-foreman/references/specialists.md`). That explicit read-only plan requires no repo
trigger declaration. An existing declaration must still be valid. A round with
work already written classifies that work:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" detect-triggers \
  --repo <repo-path> --base <recorded-base> [--head <pushed-head>] \
  --roles <role[,role...]> [--requirements <requirements.json>] \
  [--planned <planned.json>] [--decisions <decisions.json>] \
  [--bootstrap-declaration <reviewed-triggers.json>] \
  [--legacy-review-declaration <reviewed-triggers.json> --task <exact-task>]
```

Exit 0 means every fired trigger is staffed or answered. On exit 1, read the
stderr object. A writing repo with no declaration uses the one-time reviewed
bootstrap contract in `skills/herdr-foreman/references/specialists.md`;
and an `unaddressed_trigger` is staffed in the roles below or answered by a
recorded decision with its reason. Re-run the command with the updated
declaration, roles, requirements and decisions after every such change, and
plan only once it exits 0.

For an unchanged historical PR, use "Classify an unchanged legacy PR" in
`skills/herdr-foreman/references/specialists.md`. Supply its immutable subject,
empty no-write plan and accepted task-bound consultation; staff every fired
trigger instead of passing decisions. Classification never authorizes release.

A round that will split its review surface validates the partition first, then
plans it with `--partition`:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" validate-partition \
  --repo <repo-path> --base <recorded-base> [--head <pushed-head>] \
  --partition <partition.json>
```

Exit 1 names every unowned path, every overlap and every slice owning nothing,
in one run. Fix the partition and re-run; plan only once it exits 0. Save its
stdout — `plan --partition` takes that result, never the document
`validate-partition` read. Validate at the pushed head: the result's `proof`
records the repo, base and head it was proven against, and Step 12's gate
cannot check a working-tree proof. Format, ownership
payload and the seating it produces:

```text
skills/herdr-foreman/references/review-partition.md
```

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/foreman.sh" plan \
  --roles <role[,role...]> [--requirements <requirements.json>] \
  [--exclude <role>=<agent>[,<agent>...]]... [--partition <validated.json>] \
  [--judge-mode adjudication|diagnosis] \
  [--round <role>=<round-type>] [--round-context <evidence.json>] \
  --task <task-id> [--fix-round <N>] [--correction-plan <id> --work <work.json>]
```

Emits the role plan without worker contact. Under config schema 7,
`worker_kinds` records the ranked template and `assignments` records one fresh,
plan-bound live identity per seat; a later plan creates different identities.
A partitioned role is seated once
per slice as `<role>#<slice>`, and Step 10 dispatches each seat with its own
brief. A judge seat declares its mode:
`adjudication` rules on a contested verdict, `diagnosis` on the investigator's
assessment at an exhausted allowance. Pass the same `--judge-mode` to `apply`.
On exit 1, resolve the diagnostic before continuing. Apply the Step 5 constraints in `skills/herdr-foreman/references/round-setup.md`:
exclude contributors from verification, reserve the developer through early fixes,
preserve task identity and fix count, and reuse recorded correction bounds.
Tier contracts:

Operator-opted minimum-adequate worker routing follows Minimum Adequate Routing
in the reference below. Refresh selected-candidate facts, not unrelated fleet
maintenance; preserve task authority, independence, explicit pins and judgment
floors.

```text
skills/herdr-foreman/references/model-tiers.md
skills/herdr-foreman/references/dispatch-recovery.md
```

Save the plan and rationale. Before launching a batch, give one compact
explanation of selected providers, measured alternatives and each exclusion or
eligibility boundary. Use the existing planner facts through
`explain-plan --plan FILE [--snapshot FILE] --constraint-source SOURCE
--constraint-scope task|project|session|standing [--refresh]` on the resolved
`skills/herdr-foreman/foreman.sh` owner. Preserve that plan's observation time
and pagination; a later snapshot cannot rewrite an earlier selection.

Keep an operator constraint's actual source link/reference and scope in the
existing handoff or task input. On a full refresh, read that real source and
reconcile its scope; retain valid standing instructions across recovery. A
formatter reference is not verified authority. Never promote an opaque
historical owner string into a new instruction or erase an inherited constraint
without that reconciliation. If source or scope remains ambiguous, ask one
concise clarification while independent eligible work continues. The diagnostic
names unknown provenance and preserves the original exclusion.

A question about available providers is diagnostic until the operator actually
changes the constraint. `explain-plan`, including `--refresh`, changes no plan,
configuration, owner, preference or authorization. It adds no preference store,
dashboard, approval or additional worker gate.

Assign whole-suite execution to the tester, with exact-head artifacts available
to the reviewer and specialists. Stagger expensive gates sharing a constrained
CPU, memory, container service or host; keep code review and independent work
moving. Use existing assignments and check evidence, without another scheduler
or utilization ledger.
Proceed immediately to Step 6.

## Step 6 — Build the Review Package

For reviewer/tester briefs, run from a checkout holding the recorded commits:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/review-package.sh" \
  <recorded-base-sha> <pushed-head-sha> <round-reports-dir>/review-<base7>..<head7>.diff
```

Apply the Step 6 base, range, and rebuild requirements in
`skills/herdr-foreman/references/round-setup.md`. Success prints the absolute review-package path;
set it as `REVIEW_PACKAGE`. On non-zero, fix the diagnostic and retry before
composing verification briefs. Other roles need no package.
Proceed immediately to Step 7.
