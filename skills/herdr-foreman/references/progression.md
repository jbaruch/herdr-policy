# Admitted task progression

Two explicitly admitted contracts share the existing task authority owner.
Schema 1 runs a fixed prepared assignment chain. Schema 2 executes a bounded
or complex task through native implementation, independent verification,
correction, release and local cleanup. Read
`skills/herdr-foreman/references/task-workflow.md` before using schema 2.
Installing this package starts neither contract and migrates no live team.
Comparative cost, throughput and defect evidence still requires the real pilot
tracked by herdr-policy epic #1; source fixtures prove no ROI improvement.

Source, Tessl and realized ACR native installations can identify their actual
policy bytes. Native ACR startup verifies the public lock/realization ledger
and requires the installed owned bytes to match the checked target hashes.
`skills/herdr-foreman/policy-paths.py identity`, invoked
with explicit Python 3 from the selected skill, is read-only and grants no
dispatch authority. A missing, changed or ambiguous installation refuses
startup. Remote/attested task execution is not enabled by these adapters.
The native reader supports per-adapter owned skill targets in ledger schemas
1 and 2. Coordinator-owned targets may coexist in the ledger; execution from
the shared `.agents/skills` layout is not enabled by this adapter.
ACR's full public realization check can fetch locked dependencies into temporary
storage. Its metadata cache is process-local, so fresh native Stop readers also
need verification access; a failed check refuses continuation. Source/Tessl
identity checks use their local installed bytes.

## Admit one task

Run `skills/herdr-foreman/foreman.sh` through the selected installation's
resolved skill root with explicit Bash. Only the actual bound native foreman or verified remote
owner may hand off a registered, open and settled task. Admission refuses
pending sends, active enrollments, another service grant and operator holds.
It never changes an existing binding, resumes a hold or starts a worker.

`progression-admit --state OWNER --record FILE` takes an object with `task`,
`expected_generation`, `authorization`, `service_id`, absolute `lease_path`
and absolute `contract`. Authorization carries `source` and `quote`. Read the
actual generation from the task owner; an unadmitted legacy task starts at
zero. Use a dedicated lease distinct from state files and transaction locks.
The result names the new generation; admission alone authorizes no dispatch.
The state owner's ordinary read upgrades older grant records without changing
their generation or authority. An old service grant remains a prepared chain;
its saved document cannot promote it to schema-2 task execution. Read-only
previews leave old records untouched and name the required owner migration.

## Prepare a schema-1 chain

The immutable contract contains `schema_version: 1`, its exact `task` and
`steps`. Each step contains `schema_version: 1`, unique `id`, `argv`, `after`, `gate` and `inputs`.
`argv` is one prepared `apply` invocation with that task, an explicit config,
assignment plan, common/role briefs and fresh reports. `inputs` contains the
owner's `{path,sha256}` receipts for every config, plan, common, role brief and
correction-work input. Keep source inputs available for replay. No report or
GitHub-history copy belongs in this contract.

`after` names earlier steps. `gate` is `delivered` or `assessed`; delivery uses
the canonical native checkpoint and exact enrolled identity. Assessment also
requires the existing enrollment's accepted resolution. A closed enrollment
uses its captured ledger prefix, current canonical accepted assessment, report
contract and native final source; it does not require the removed pane. Missing,
changed or contradictory evidence wakes the foreman. Neither gate supplies
acceptance of the task. Supported responsibilities, budgets, refusal predicates
and parser contracts live in `skills/herdr-foreman/foreman/progression_service.py`.
Closed dependencies require clear classifier gates. The actual owner apply
rechecks these gates under their existing lock and keeps that lock through
dispatch. Evidence failures return a bounded refusal naming the failed stage
and the required recovery action.
The admitted CLI clones the native transport with a supervision-owner boundary.
Each invocation checks the live binding and unresumed holds under the same lock
used by hold/rebind writers and keeps that lock through transport. Enrollment
transactions run outside that short boundary. A hold or rebind that wins the
lock prevents transport; an in-progress invocation prevents their commit.

The owner captures verified config/plan/work bytes for apply and checks the
frozen brief bytes before worker effects. A mutable replacement cannot change
the admitted assignment. This adapter refuses arbitrary commands and release
roles; use the existing verified release owner for that boundary.

## Prepare a schema-2 task

The immutable object contains exactly `schema_version: 2`, `task`, `risk`,
`repository`, `config`, `common`, `briefs`, `artifact_directory`, `effects`,
`publication` and `acceptance`.
`skills/herdr-foreman/foreman/workflow_contract.py` owns validation
and bounds; unsupported or missing facts fail before worker launch.

`risk` supplies every schema-1 fact accepted by
`skills/herdr-foreman/foreman/workflow_profiles.py`, without defaults.
Bounded work combines independent review and testing; complex work
uses separate identities. Sensitive work and required specialist coverage
currently create an explicit pre-implementation exception. Do not misclassify
the work to avoid that boundary.

`repository` names the exact GitHub `owner/repo`, absolute additional `worktree`,
`branch` and `base_branch`. Admission requires that clean writer at the task's
registered base, its actual origin and a distinct base checkout. Existing
implementation is not adopted as a new task.

`config`, `common` and each `briefs` entry are `{path,sha256}` receipts of
nonempty UTF-8 files. The config supplies assignment-scoped worker kinds with
tier tables. Use the co-shipped common and selected role inputs:

```text
skills/herdr-foreman/templates/workflow-common.md
skills/herdr-foreman/templates/workflow-developer.md
skills/herdr-foreman/templates/workflow-reviewer.md
skills/herdr-foreman/templates/workflow-tester.md
skills/herdr-foreman/templates/workflow-release.md
```

A bounded task omits the tester role.
The executor appends actual scope, policy paths, native report paths and current
evidence; templates cannot substitute for those owner-derived facts.

`artifact_directory` is a fresh, owner-controlled absolute directory outside
the writer, with an existing parent. Admission reserves it by exclusive creation;
an existing directory, including an empty one, is preserved and refused. Keep
frozen templates outside this new directory. It holds current plan/common inputs, role briefs and native reports
plus narrowly named delivery/review artifacts. It is not a history directory.
Workers consume the specific inputs named in their brief, never a recursive
`.hr` or owner-state dump. GitHub remains the change and review history.

After verified acceptance, selected publications and Git teardown, delivery
schema 2 retires the private directory through the existing cleanup intent.
It moves the directory and each file into its exclusively owned quarantine
before checking the captured inode and bytes, then deleting. The bounded
manifest holds at most 256 identities; each batch holds at most 32 receipts.
Unknown entries, changed evidence, links, open report gates and unresolved enrollments preserve
the source or quarantine. Restart resumes the same intent. The
`.herdr-retire-` namespace belongs exclusively to this lifecycle.
Owner-proved unsent attempts retire only their byte-bound unused briefs, with
no active enrollment or report; their canonical no-send evidence remains.

The primary owner migrates delivery 1 on read; run the owner state command
before a read-only preview or restarted executor. Already completed history is
marked `legacy_preserved` without a directory sweep. Older delivery-1 readers
refuse the new lifecycle. Keep an owner that reads delivery 2 for in-flight
cleanup. Canonical receipts and the GitHub closure reference retain completed
history; the CLI returns a compact lifecycle view, never its file manifest.

`effects` is a unique list drawn from `write`, `push`, `open_pr`, `merge` and
`publish`. All four source effects are required; publish matches the channels.
`publication` contains `tessl` (null or `{workspace,plugin}`), `acr` (boolean)
and `workflow` (null without publication, otherwise the exact merge-triggered
publisher). `acceptance` contains `kind` (`merge`, `deployment` or `operator`)
and one to sixteen criteria. Only merge acceptance is automated currently;
other kinds remain explicit exceptions until their actual evidence owner acts.

## Run and observe

`progression-run --state OWNER --task TASK --generation N --service-id ID`
claims the existing grant and dedicated kernel lease. `--once` performs one
tick. The native adapter uses the actual inherited Herdr connection; never
construct `HERDR_ENV`, a pane or a session identity from saved records.
The actual `HERDR_PANE_ID`, live native foreman session and current working
directory must match the bound foreman. Startup, task writes, liveness and
native transport verify that caller; another managed pane has no authority
from knowing the task, generation or service ID. Schema-2 admission also
requires this native caller; verified remote admission remains schema 1 only.
Retain the process's actual execution handle; a background command submission
alone proves neither a running executor nor continuation at Stop.

The loop sleeps without a model relay, checks dependencies outside the shared
transaction lock and writes only a current intent or cursor transition.
Unchanged waiting polls write nothing. Results contain `wake_agent` and a
bounded `data` packet. Waiting stays observational. Exceptions wake the foreman
with the task, generation, current intent and refusal; no count or timeout
permits self-approval. Current evidence retrieval follows
`skills/herdr-foreman/references/working-memory.md`.
The process returns this packet on its retained execution handle; it supplies
no generic native asynchronous message service. Keep that handle available for
the caller's completion/exception delivery rather than relying on a PID file.
Heartbeat transaction contention retries within the existing liveness grace;
authority failures still stop immediately. Persistent contention loses health
instead of authorizing takeover or repeating an effect.
Foreground transaction contention returns an observational waiting result;
the next tick reads the original intent and canonical readback before effects.

## Recover and return

An applied operation lost before cursor commit replays the same owner receipt
without another send. Missing, partial or uncertain readback preserves the
pending intent and stops progression. A dead process or free lease proves no
effect outcome. Reconcile through the existing dispatch/native owners; the
initial adapter does not automatically clear an ambiguous service intent.

After the effect owner supplies its operation-specific canonical readback and
settles its enrollments or retained probes, the verified bound foreman may run
`progression-reconcile --state OWNER --record FILE`. The record contains `task`,
actual `expected_generation`, exact `intent`, explicit `authorization` and,
for measurement, a schema-1 `readback` with `kind` and canonical `sha256`.
The service lease must be free. This clears only that pending intent, leaves
the schema-1 cursor unchanged and records one owner reconciliation receipt. It does not
dispatch, resume a hold or accept work. Missing, uncertain or partly applied
sets remain pending. The same completed reconciliation replays without a write.
Associated transport-retry identities also refuse this initial reconciliation
adapter. The original no-send row never proves a later attempt had no effect.
Pre-reservation refusals without durable dispatch proof remain pending for
owner recovery; process exit or a refusal message alone does not clear them.

For schema 2, reconciliation accepts only the exact pending launch after every
named dispatch is owner-proved `not_sent`, all task enrollments are settled and
no report exists. It retires the intent and current plan, preserving the task,
generation, original base and correction counter. Subsequent execution selects
a fresh native identity; the old no-send row remains canonical evidence.

A schema-2 measurement uses `intent_not_started`, `snapshot_completed` or
`probes_closed_incomplete`. The first hashes the durable intent and requires
`effects_started: false`. A completed snapshot must hash to exactly one state-owner
snapshot and match the intent's saved `--now`, current native measurement context,
captured config and complete configured worker set. A probe readback must hash to
one canonical closed startup/cleanup row, match the captured config and saved
timestamp, leave no pending or live disposable probe, and records only an
incomplete measurement outcome. Missing processes, dispatches, reports and timeouts
are not readback. Legacy started measurements without a saved timestamp can use
only one unambiguous exact probe/config receipt; a later snapshot is never adopted.

Use `--readback-current` on the existing `progression-reconcile` command to derive
the measurement evidence from its owners. Its record needs only the task,
expected generation, pending intent and existing authorization. The owner selects
one exact snapshot or retained probe attempt and records its actual digest;
callers need no ledger dump or handwritten hash. Ambiguous or missing evidence
leaves the intent pending. Repeating a settled request reads its existing receipt.
Policy-change refusals name the expected and observed version/digest in the
current exception, without loading policy history.

`progression-resume --state OWNER --record FILE` retries a restored schema-2
observation or cleanup exception. The record contains `task`, actual
`expected_generation`, the current packet's `exception_digest` as `exception`,
and explicit `authorization`. The bound foreman, admitted policy/contract and
binding must still match, the lease must be free and operator holds must be
resumed through their own owner first. Resume restores the packet's exact saved
phase; it does not reset jobs, counters, confirmed channels or pending effects.
An already applied dispatch or closed enrollment is read back; an uncertain
native effect refuses resume. Cleanup uses its fixed, idempotent readback.
Disputes, changed scope, exhausted corrections, specialist work and missing
acceptance are decisions, not generic retries. The exact retryable packet codes
are owned by `skills/herdr-foreman/foreman/workflow_recovery.py`.

A healthy schema-2 executor can cover only its exact current task/member
obligations at Stop. Its current supervision row must match the live process,
kernel lock owner, admitted generation, contract, policy and binding. Pending
unknown effects and exceptions cover nothing. Schema-1 chains never gain Stop
authority from a heartbeat. No continuation check reconstructs a legacy round
or reads its historical contracts to decide whether it can cover work.

The bound foreman may record current exception assessments through the normal
owners without taking the service's dispatch lease. Returning a task requires
settled dispatches/enrollments, no pending service intent and a free lease.
`progression-return --state OWNER --record FILE` takes `task`, actual
`expected_generation` and explicit `authorization`; it increments generation
and clears service capabilities. Do not edit owner files, reset a cursor,
delete a lease, duplicate dispatch or infer a successful outcome to recover.
After return, a new schema-2 admission binds the actual loaded policy and a fresh
artifact directory. It increments authority generation and preserves the existing
task record, base, assignment/snapshot/event history and cumulative correction
value; the original first-measurement counter remains zero rather than being
reclassified as an attempt.
