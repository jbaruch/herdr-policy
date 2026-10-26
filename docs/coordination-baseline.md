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
input shipped here. Retained owner, native and ledger sources support the
conservative export below. Its explicit cohort and stricter report-binding
requirements produce a new sample; it does not reproduce the original aggregate
denominators by assertion. Fixtures prove calculations, not observed ROI.

## Reproduce an owner-evidence sample

Freeze private copies of the owner and its supervision sidecar before exporting.
Keep the originals, copies, transcripts, ledgers and source maps outside Git.
The exporter reads state schema 11, recovery-store schemas 18/19/20 and supervision
schema 1; an unsupported version fails without migrating or writing an owner.
Select a trusted extracted Herdr source checkout for its existing native and
task-ledger readers. The default is this repository after extraction.

```sh
python3 scripts/export_owner_baseline.py --owner /private/baseline/owner.json --supervision /private/baseline/supervision.json --start 2026-10-10T00:00:00Z --end 2026-10-15T07:05:37Z --provenance-output /private/baseline/provenance.json > /private/baseline/snapshot.json
python3 scripts/coordination_baseline.py /private/baseline/snapshot.json
```

Use `--herdr-source /path/to/trusted/checkout` when evaluating an extraction
candidate from a separate measurement checkout. Provenance is created with mode
0600 outside the repository. Its schema 3 records the normalized UTC observation
window, Python version, input,
exporter and evidence hashes, every owner Python module's hash, and exclusion
counts. An identical repeat is permitted; a differing
existing provenance file requires a fresh output path. The CLI emits no native
text, raw task/session identities, worker names or private paths in its snapshot.

Assessment timing uses the resolution receipt's byte size and SHA-256. Parse
only the verified original prefix when a ledger has later appends. Changed,
short or unavailable captured bytes leave assessment time unknown and add an
exclusion diagnostic. A new hash of an unverified replacement is not evidence
for the original assessment.

The cohort includes tasks registered or attempted inside the half-open window.
Transport events separate retries and project each attempt at the observation
boundary. Assignment timing uses the send event; later sends and outcomes do
not rewrite that boundary. A pending send has no native or supervision timing
until its own recorded result is available. Evidence from a later retry is never
borrowed for an earlier attempt. Imported legacy rows without transport events
retain their coarse reservation timing; that timing is not a precise send receipt.
Applied, `sending` and `sent_but_not_started` dispatches remain assignment envelopes. Confirmed
unsent attempts retain their task in the cohort but create no busy worker.
Pre-send reservations likewise retain their task without claiming worker activity.
Task state at the window boundary uses the canonical owner closure reader on
events and assignments available by that boundary. A later applied developer
assignment reopens the task; uncertain chronology fails instead of claiming closure.
Assignment and enrollment IDs, task and worker must agree. A missing or
conflicting identity remains unknown. Original/refined identities and frozen
observations of resolved enrollments supply candidates. An observation requires
a resolution before the window end, matching pane evidence, and no identity,
availability or observation error. It still needs native proof.

The canonical source reader must prove the candidate session's latest completed
assistant message ends with that enrollment's bare report marker. Native start
and completion come from that turn's timestamps, not a status banner, report
mtime or tool exit. Completion must fall after dispatch and within the window.
Active observations without an archival time boundary remain unknown. Sources
whose latest message changed or cannot be read are excluded, even when an older
completion may exist. Grok's source timestamps use Unix seconds; other supported
native records use offset-aware ISO timestamps.

Assessment is the earliest matching explicit assessed assignment event in a
canonical ledger bound to the original state identity, task, dispatch, worker
and report, before the window end. Resolution is the recorded owner timestamp.
Report size comes from an in-window report observation. Held-task membership
comes from the hold's explicit enrollment dispositions. A wait for the user maps
to `operator`; other hold reasons remain `unknown`. Holds are never subtracted
from delay. Exclusion counts describe attempted reference reads and are not all
unique assignments.

An October 18 rerun over the window above retained 30 tasks and 392 assignment
envelopes: 368 had report-bound native completion and 24 remained unknown. The
resolution-delay and receipt-verified assessment-delay samples each had 344 pairs.
These differ from the original latest-day samples and cannot replace their
reported numbers. All 30 task classes/risks and foreman effort remain unmeasured
in this automatic export. Four owner closures prove neither integration nor
deployment nor acceptance. Join independently verified outcome/effort and
class/risk evidence before a comparison; do not interpret absent metrics as zero.

| Paired interval | Pairs | Median | Nearest-rank p90 |
| --- | --- | --- | --- |
| Native start to completion | 368 | 7.65 min | 17.64 min |
| Native completion to assessment | 344 | 18.22 min | 73.13 min |
| Native completion to owner resolution | 344 | 19.52 min | 73.14 min |

The receipt-verified rerun parsed original captured ledger prefixes, including
valid prefixes in subsequently appended ledgers. One unusable ledger reference
and 15 native finals not bound to their reports remain exclusion diagnostics.
The two subsequent delays overlap and must not be added together.

## Measurement input and summaries

The packaged [measurement reference](../skills/herdr-foreman/references/coordination-metrics.md)
owns the input and summary schemas, queue-state interpretation, overlap rules
and bounded installed command. The repository's
`scripts/coordination_baseline.py` remains a compatibility entrypoint to that
same calculator. Installed `measurements.py collect` uses the shared frozen-source
producer and returns a bounded summary or one private report. The development
export command above retains explicit selection of an older trusted reader.

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

Run `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_coordination_baseline.py` and
`PYTHONDONTWRITEBYTECODE=1 python3 tests/test_owner_baseline_export.py` for the
calculation and normalization fixtures. The retained-source rerun supplies
observational evidence; the live comparative pilot remains separate under #18.
