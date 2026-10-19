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
and rehashes the installed owned files. `policy-paths.py identity`, invoked
with explicit Python 3 from the selected skill, is read-only and grants no
dispatch authority. A missing, changed or ambiguous installation refuses
startup. Remote/attested task execution is not enabled by these adapters.

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
`publication` and `acceptance`. `foreman/workflow_contract.py` owns validation
and bounds; unsupported or missing facts fail before worker launch.

`risk` supplies every schema-1 fact accepted by `workflow_profiles.py`, without
defaults. Bounded work combines independent review and testing; complex work
uses separate identities. Sensitive work and required specialist coverage
currently create an explicit pre-implementation exception. Do not misclassify
the work to avoid that boundary.

`repository` names the exact GitHub `owner/repo`, absolute additional `worktree`,
`branch` and `base_branch`. Admission requires that clean writer at the task's
registered base, its actual origin and a distinct base checkout. Existing
implementation is not adopted as a new task.

`config`, `common` and each `briefs` entry are `{path,sha256}` receipts of
nonempty UTF-8 files. The config supplies assignment-scoped worker kinds with
tier tables. Use the co-shipped `templates/workflow-common.md` and the selected
`workflow-developer.md`, `workflow-reviewer.md`, `workflow-tester.md` and
`workflow-release.md` as the role inputs. A bounded task omits the tester role.
The executor appends actual scope, policy paths, native report paths and current
evidence; templates cannot substitute for those owner-derived facts.

`artifact_directory` is a private, owner-controlled absolute directory outside
the writer. It holds current plan/common inputs, role briefs and native reports
plus narrowly named delivery/review artifacts. It is not a history directory.
Workers consume the specific inputs named in their brief, never a recursive
`.hr` or owner-state dump. GitHub remains the change and review history.

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

## Recover and return

An applied operation lost before cursor commit replays the same owner receipt
without another send. Missing, partial or uncertain readback preserves the
pending intent and stops progression. A dead process or free lease proves no
effect outcome. Reconcile through the existing dispatch/native owners; the
initial adapter does not automatically clear an ambiguous service intent.

After the dispatch owners prove every expected member of a pending step
`not_sent` and settle its enrollments, the verified bound foreman may run
`progression-reconcile --state OWNER --record FILE`. The record contains `task`,
actual `expected_generation`, exact `intent` and explicit `authorization`.
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
are owned by `foreman/workflow_recovery.py`.

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
