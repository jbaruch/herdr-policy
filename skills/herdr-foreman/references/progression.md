# Admitted task progression

This initial adapter runs prepared implementation and independent-verification
assignments while the foreman handles other decisions. It retains the normal
role, native identity, report, correction, supervision and release contracts.
It supplies no unattended Stop continuation, automatic acceptance, release
adapter or risk-profile activation. Keep the real execution handle and existing
fleet-supervision obligations. The prototype and rollout remain tracked in
herdr-policy issues #8–#12 and #18; planning issues grant no runtime authority.
Policy identity supports source, Tessl and realized per-adapter ACR installations.
Native verification checks the consumer declaration, public lock/realization
metadata and unchanged owned bytes. A fresh public ACR check can fetch locked
dependencies and requires registry access. CI exercises the installed progression
entrypoint's policy selection before entering authority; live admission and
rollout still require their own verified evidence. The shared `.agents/skills`
layout is outside this identity adapter.

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

## Prepare current inputs

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

## Run and observe

`progression-run --state OWNER --task TASK --generation N --service-id ID`
claims the existing grant and dedicated kernel lease. `--once` performs one
tick. The native adapter uses the actual inherited Herdr connection; never
construct `HERDR_ENV`, a pane or a session identity from saved records.
Remote delivery progression is not enabled by this initial adapter.

The loop sleeps without a model relay, checks dependencies outside the shared
transaction lock and writes only a current intent or cursor transition.
Unchanged waiting polls write nothing. Results contain `wake_agent` and a
bounded `data` packet. Waiting stays observational. Exceptions wake the foreman
with the task, generation, current intent and refusal; no count or timeout
permits self-approval. Current evidence retrieval follows
`skills/herdr-foreman/references/working-memory.md`.

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
the cursor unchanged and records one owner reconciliation receipt. It does not
dispatch, resume a hold or accept work. Missing, uncertain or partly applied
sets remain pending. The same completed reconciliation replays without a write.
Associated transport-retry identities also refuse this initial reconciliation
adapter. The original no-send row never proves a later attempt had no effect.
Pre-reservation refusals without durable dispatch proof remain pending for
owner recovery; process exit or a refusal message alone does not clear them.

The bound foreman may record current exception assessments through the normal
owners without taking the service's dispatch lease. Returning a task requires
settled dispatches/enrollments, no pending service intent and a free lease.
`progression-return --state OWNER --record FILE` takes `task`, actual
`expected_generation` and explicit `authorization`; it increments generation
and clears service capabilities. Do not edit owner files, reset a cursor,
delete a lease, duplicate dispatch or infer a successful outcome to recover.
