# Coordination measurements

Summarize a sanitized snapshot offline. This operation follows this reference;
live team-round steps govern native work. It returns observational evidence
and grants no task, release or production authority. Return the summary or
receipt and finish this skill here. On a non-zero exit, report the diagnostic
and finish here without starting live team work.

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
python3 "$HS/measurements.py" /private/baseline/snapshot.json
```

The command's stdout uses the shared `foreman/context_output.py` byte budget.
For a complete report larger than that budget, retain the whole selected cohort
and request one private output file:

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-foreman/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
python3 "$HS/measurements.py" /private/baseline/snapshot.json --output /private/baseline/report.json
```

`--output` creates a mode-0600 report outside repositories and installed
packages. Its file schema 1 contains the input byte digest, calculator digest,
Python version and summary schema
2. Stdout returns a schema-1 receipt with path, digest, byte count and cohort
counts. Identical repeats preserve the existing file; changed or foreign
outputs refuse. An I/O failure may leave its newly created partial file; preserve
that file and select a fresh output path after repairing the cause. Keep the finite comparison report and its source snapshot
private while evaluating the preregistered cohort; publish supported aggregates
and evidence links in GitHub. Once the comparison and evidence obligations are
closed, retire its local artifacts. Reports never become a must-load history floor.

`MAX_SNAPSHOT_BYTES` in `foreman/coordination_metrics.py` owns the input budget.
The command reads only the selected snapshot, performs no network or native
team operations, and creates a file only for an explicit `--output`. Existing
repo commands through `scripts/coordination_baseline.py` use this same owner.

## Sanitized snapshot

The CLI reads only this file, emits one bounded summary or report receipt, and performs no network
or team-state operations. A malformed export exits 2 with a diagnostic and no
measurement. Keep snapshots and their raw-source maps outside the repository.

The exporter writes input schema 2. The analyzer also accepts schema 1 with
missing endpoint times treated as unmeasured. Both have these required fields:

| Field | Contract |
| --- | --- |
| `schema` | Integer `1` or `2` |
| `window` | `start` and `end`, offset-aware ISO timestamps; fixed, positive-duration observation window |
| `tasks` | Array with unique nonempty `id`, explicit `state`, `class`, `risk`; include failed, blocked and unknown work |
| `assignments` | Array with unique `id`, listed `task_id`, `native_match` of `matched` or `unknown`, and `dispatched_at` |
| `activity_minutes` | Optional unique minute-aligned timestamps inside the observation window; no samples means unmeasured activity |

Optional task records:

- `integration`, `deployment`, `acceptance`: each has an `at` timestamp inside
  the observation window and an `evidence` array of opaque references. Both are
  required to count an evidenced stage. The exporter verifies the source;
  references alone do not independently prove an external effect. Omit events
  outside the window rather than silently counting preexisting outcomes.
- `foreman`: known `active_seconds`, `exec_calls`, `output_bytes`, and
  `reconstruction_bytes`. Each source event contributes once across the cohort;
  split a shared event by a recorded allocation or mark attribution unknown.
  A missing/null measurement remains unknown. Do not add overlapping activity.
- `rework_rounds`, `escaped_defects`: nonnegative measurements or null. An
  unmeasured defect rate is not zero defects.
- `holds`: entries with `start`, `end` (null when open), and `reason` from
  `operator`, `policy`, `dependency`, `quota`, `outage`, `verification`, `unknown`. Preserve
  operator/policy/dependency holds; the analyzer lists them without summing them
  into waits or subtracting them as if every held second were avoidable.

Optional assignment fields are `native_started_at`, `native_completed_at`,
`assessed_at`, `resolved_at`, and `report_bytes`. Native timestamps require a
verified enrollment/session match in the exporter. Retain unmatched records;
do not infer native completion from a status banner or report modification time.

Schema 2 also accepts `assessment_state` and `resolution_state`: `completed`,
`pending`, or `unmeasured` at the observation boundary. An explicit pending
state requires source evidence of an open queue at that boundary. Missing
time alone never proves pending work. A completed state without its measured
time remains excluded from latency and exposure calculations.

The exporter marks canonical owner resolutions as completed or pending when
their enrollment is available. Unavailable enrollments remain unmeasured.
Assessment timing needs the verified ledger receipt; unavailable or changed
receipts leave assessment unmeasured, including after owner resolution. The
exporter cannot prove an open assessment queue from an absent receipt.

Before export, join immutable enrollment and native-session identities, retain
the match decision in a private source map, fix the window, and record task
selection/exclusions. Preserve missing evidence and changed/invalidated heads.
Normalize clocks to offset-aware timestamps; never replace negative delays with
zero. Remove transcript bodies, usernames, credentials, repository-local paths
and production data; opaque ids preserve joins. Exporter/version and source
digests belong in the private provenance record, not a public transcript dump.

## Summary fields and interpretation

`foreman/coordination_metrics.py` owns derived summary schema 2. Readers select
that supported version explicitly. Regenerate a summary from its sanitized
snapshot; this operation never migrates or rewrites source evidence, owner
state or previously saved reports.

`latency_seconds` reports native work, assessment and resolution distributions.
Read each denominator and its named exclusions with that distribution; unknown
or unusable endpoints remain visible. The calculations are owned by `paired`
and `distribution` in the calculator. Assessment and resolution delays overlap
and cannot be added. A queue delay alone does not establish avoidable effort.

`waiting` distinguishes verified pending queues from unmeasured endpoints.
Each queue reports age statistics, an oldest list, omitted counts, known
`wait_task_seconds`, covered tasks and exclusions. `waiting` and `union_seconds`
in the calculator own the exposure calculations; `OLDEST_PENDING_LIMIT` owns
the list budget. These are known waiting exposures across tasks, not foreman
active effort. Read their coverage and exclusions together. Assessment and
resolution totals overlap and cannot be added. Blocked work remains included.
Holds retain their separate reason categories and never prove presumed waste.

`activity` describes possibly busy envelopes, not distinct physical workers.
Duplicate ownership or a reused native session can overcount workers. This
conservative proxy is not exact fleet utilization and must not be relabeled as
the historical concurrency estimate without checking the private original
sampling and identity-deduplication method. `summarize` owns its sampling
calculation.

`effort` retains known and unknown measurement counts and reports output per
evidenced accepted outcome when measurable. Its calculations live in `totals`
and the effort projection in `summarize`. A null value is unmeasured, not zero.
Failed and blocked work remains in the cohort. Compare bytes with bytes and
time with time; no bytes-to-tokens or tokens-to-dollars conversion is assumed.
GitHub integration, actual deployment and measured acceptance remain separate
outcomes. An exporter assertion is distinct from verified external readback.
