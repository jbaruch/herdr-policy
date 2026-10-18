# Coordination baseline and comparison contract

Part of [#3](https://github.com/jbaruch/herdr-policy/issues/3), under
[epic #1](https://github.com/jbaruch/herdr-policy/issues/1). This analysis grants
no task, worker, release or production authority.

## Historical observation

The [October 15 evidence record](https://github.com/jbaruch/herdr-policy/issues/1)
is the source of these historical aggregates. The policy snapshot is
[`c96e66bf922b884b0e2bca67ebdada4af14797bf`](https://github.com/jbaruch/coding-policy/tree/c96e66bf922b884b0e2bca67ebdada4af14797bf),
coding-policy 0.3.405. GitHub activity spans October 8, 2026 07:05:37 UTC through
October 15, 2026 07:05:37 UTC. Native foreman observations span October 10–15;
the two windows and their populations must remain distinct.

| Measure | Recorded result | Limit |
| --- | --- | --- |
| Application delivery | 13 merged PRs across 11 active repositories | Merge does not prove deployment or user acceptance; changes are not all attributable to this foreman |
| Assignments | 548: 485 fleet, 63 policy repair | Intake and investigation are included; assignments are not outcomes |
| Native identity matches | 539 of 545 eligible enrollments | Six unmatched envelopes remain possibly busy |
| Extant fleet reports | 467, about 6.38 MB | Missing reports remain missing; bytes are not tokens |
| Foreman work | 3,110 exec calls; roughly two million output tokens in the saved session | Inconsistent cumulative/per-request token counters prevent a precise billed total |
| Foreman activity sample | 18.64 hours; mean worker concurrency 2.64; 16.2% zero-worker buckets; 53.9% at most two | One-minute buckets with usage/tool events; neither wall-clock capacity utilization nor CPU time |
| Latest-day completion/resolution pairs | 250; median native work 7.09 min; subsequent resolution delay 22.52 min | Paired sample; sibling work, holds and prioritization can contribute |
| Latest-day assessed subset | 179; median native work 7.02 min; subsequent assessment delay 11.40 min | A different denominator; these delays overlap resolution delays |
| Compactions | 25; median 122 tool calls between them | Does not establish semantic fidelity or causal contribution to delivery delay |
| Completed policy-blocker holds | Seven; about 44.9 hours, plus one still open | Operator-directed holds; no assumption that all elapsed time was avoidable |

Useful verification and poor convergence both occurred. Main task 975 found a
missing addition oracle in seven assignments. Main task 981 consumed 58
assignments, discovered real message-loss/startup defects late, and remained
open. Admin task 559 consumed 20 assignments; source gates did not prevent a
production execution from deleting persisted cadence history. Include these
outcomes and the blocked cases when interpreting apparent coordination savings.

The public aggregates cannot reconstruct the original per-enrollment timelines
or tail distributions. The original private audit working directory is not an
input shipped here. Rerunning the historical results requires the operator-held
native, owner, report and GitHub evidence plus a normalized export. The fixture
tests below prove calculations; they do not regenerate these observed numbers.

## Sanitized snapshot

Run `python3 scripts/coordination_baseline.py /private/path/snapshot.json`.
The CLI reads only this file, emits one JSON summary, and performs no network
or team-state operations. A malformed export exits 2 with a diagnostic and no
measurement. Keep snapshots and their raw-source maps outside the repository.

Schema 1 has these required top-level fields:

| Field | Contract |
| --- | --- |
| `schema` | Integer `1` |
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

Before export, join immutable enrollment and native-session identities, retain
the match decision in a private source map, fix the window, and record task
selection/exclusions. Preserve missing evidence and changed/invalidated heads.
Normalize clocks to offset-aware timestamps; never replace negative delays with
zero. Remove transcript bodies, usernames, credentials, repository-local paths
and production data; opaque ids preserve joins. Exporter/version and source
digests belong in the private provenance record, not a public transcript dump.

## Calculation and interpretation

Latency records pair each assignment's timestamps. Native work is start to
native completion; assessment delay is native completion to contract assessment;
resolution delay is native completion to owner resolution. Report each sample's
own denominator, median and nearest-rank p90. Unknown identity, missing endpoints
and reversed clocks have separate exclusion counts. Never add assessment and
resolution delays: they overlap. No queue delay is automatically classified as
avoidable orchestration.

Activity is a conservative envelope-overlap proxy at the supplied one-minute
foreground buckets. Matched envelopes use native start/completion when present;
missing native boundaries widen to dispatch/resolution or the observation end.
Unknown envelopes remain possibly busy from dispatch to resolution/window end.
The output says **envelopes**, not physical workers: duplicate ownership or a
reused native session can overcount workers. This is not exact fleet utilization
and must not be relabeled as the historical concurrency estimate without checking
the private original sampling and identity-deduplication method.

Effort totals retain known/unknown counts. Cohort output per evidenced accepted
outcome includes failed and blocked work in the numerator. It is null when no
accepted outcome exists or any output measurement is unknown. Compare bytes
with bytes and time with time; no bytes-to-tokens or tokens-to-dollars conversion
is assumed. GitHub integration, actual deployment and measured acceptance are
reported separately. An exporter assertion is distinct from verified readback.

## Preregister the ten-task pilot

Before its first assignment, record the next ten suitable coherent tasks, risk
and complexity mix, eligibility/exclusion rules, outcome authority, active task
authority, baseline/comparison windows and rollback boundary. Retain failures,
operator holds and blocked tasks. Preserve independent verification and all
required release/production checks. No retrospective choice of easy successes.

Compare acceptance/deployment evidence, foreman activity and output, reconstruction
volume, paired stage-delay distributions, repeats/rework and escaped defects.
Report denominators and case-level explanations; a busy fleet or smaller packet
alone cannot establish value. A production loss or waived verification fails
promotion. Otherwise report whether lower effort and waiting are supported,
contradicted or inconclusive at comparable delivered value and task mix. Ten
tasks provide descriptive evidence, not a statistical claim of equal safety.
If tradeoffs or missing evidence prevent a decision, preregister more observations
or roll back. No savings percentage or universal review-round cutoff is assumed.

Run `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_coordination_baseline.py` for the
synthetic calculation checks. Actual historical export and the live pilot remain
separate evidence requirements under #3 and #18.
