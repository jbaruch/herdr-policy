# Adapt Drover's progression model through Herdr owners

Date: 2026-10-18. Decision: selected for implementation; runtime rollout and comparative outcomes remain unverified.

Tracking: [epic #1](https://github.com/jbaruch/herdr-policy/issues/1), [architecture #5](https://github.com/jbaruch/herdr-policy/issues/5).

## Problem and evidence

The extraction changes package ownership. It does not change the foreground service queue. The historical audit in the epic found a median 22.52-minute completion-to-resolution delay across 250 paired assignments, compared with 7.09 minutes of native work. Those overlapping intervals do not establish how much delay is avoidable. Repeated reconstruction also returned 241,746 bytes in six calls after one compaction. Neither package size nor these samples prove a savings percentage.

We inspected Drover at [4a49c72c487c000eaf9134df2fe241741109acb7](https://github.com/andrebrov/drover/tree/4a49c72c487c000eaf9134df2fe241741109acb7), also the upstream head on this date. Its `fleet-watch` consumes durable announcements and routes review/correction work without lead-model turns. `fleet-batch-land` isolates a failing branch, checks the baseline, serializes its worktree, retries Git races, and verifies the result against the remote. These are implemented mechanisms, not evidence that our fleet will deliver faster.

Existing Herdr already provides durable task/dispatch records, native assignment identity, report observation, correction authorization, closure proofs, fresh workers, and remote attestations. Retaining those capabilities is migration work avoided; it is not a new coordination benefit.

## Alternatives and maintenance cost

Costs below identify work and continuing ownership; they are not invented engineering-hour estimates.

| Alternative | Required adaptation | Continuing cost and requirement fit |
| --- | --- | --- |
| Full Drover adoption | Replace the Beans board with GitHub task/repository identities; adapt roster/harness discovery, remote authority, PR review/publication, effect guards, and approval binding. Migrate or replace existing owner records. | Own a broad compatibility layer or an upstream fork. Its macOS services and single project checkout do not cover our supported execution environments. Running both dispatchers would violate single authority. |
| Adapt selected components | Implement the completion/review/correction state machine over Herdr owners; use a portable service entry point. Adapt landing behavior through the existing GitHub release contract. | Maintain one small progression owner plus adapters. Reuse upstream test scenarios where relevant. Avoid duplicating the board, native identity, report, and release owners. |
| Reuse current owner APIs only | Add task-scoped service authority, an event consumer, recovery journal, and permitted transition policy. Current APIs still require a bound foreman and some model judgments. | Good foundation for component adaptation. API reuse alone leaves the serial queue intact unless routine transitions execute independently. |
| Targeted foreground improvements | Reduce reads and combine existing commands without changing authority or process lifetime. | Lowest initial migration cost, but the foreground model remains the progression bottleneck. Does not meet the background-progress acceptance criterion. |

Select component adaptation using current owner APIs. Do not transplant `fleet-watch`, its board/store, or `fleet-batch-land` as a second manager. Do not introduce Beans. Do not fork Drover's entire runtime. Reconsider a particular component when adaptation is demonstrably smaller than an equivalent maintained implementation.

The initial landing adapter uses the existing GitHub PR/review/publication path. Drover's batch lander pushes directly to main and cannot substitute for those gates. Its failure isolation, worktree ownership, post-push readback, and race scenarios inform our tests. A later GitHub merge-queue/batching optimization needs separate measured justification.

## Ownership and normal path

Each task has one outcome owner and one progression authority. They are distinct responsibilities: the owner implements and corrects the coherent change; the executor advances already authorized transitions. A task cannot be enrolled in both legacy foreground dispatch and background progression.

1. The operator or verified existing owner records the task's repository, scope, outcome owner, risk profile, permitted effects, dependency/hold state, and release contract. Admission is explicit; scanning an issue does not grant authority.
2. The executor claims the task under the owner's lock and fencing generation. It dispatches a ready assignment through Herdr's native transport, with a stable intent identity and durable expected-report binding.
3. A completion observation triggers native identity/report/delivery checks. A banner or a report headline alone cannot advance acceptance. Missing or contradictory evidence creates a recovery obligation.
4. A suitable bounded change uses one outcome owner and an independent verifier covering review and test responsibilities. Higher risk or uncertainty can require additional independent responsibilities. The risk-profile implementation must amend conflicting fixed-role rules before this path is enabled.
5. A verifier's blocking findings route to the same outcome owner with the outstanding findings and affected change identity. A clean bound verdict plus required checks makes the release transition eligible. Classifier uncertainty routes to an exception, never to approval.
6. The release adapter runs the repository's required PR, CI, policy/Copilot review, merge, and per-channel publication confirmation. Required gates remain gates. A model turn is needed only when the recorded contract calls for a judgment or unresolved decision.
7. Integration, deployment, and acceptance are separate events. A confirmed merge does not imply deployment; deployment does not imply the measured user outcome. Closure requires the admitted task's actual acceptance evidence.

The executor operates while the global foreman session is idle or absent. That requires an explicit service authority, not a fabricated foreman pane/session. No current owner guard may be bypassed to make an initial daemon appear functional.

The foreman handles priorities, cross-task dependencies, profile changes, and exceptions requiring judgment. It does not narrate ordinary completion, schedule already-required verification, or relay deterministic correction messages. Worker occupancy is not a success metric.

## Component and API contracts

The following existing interfaces were inspected in extraction commit `697870050781ad4b503ce5b9cbd6ad4e42e7ba61`. They remain authoritative for their owned records.

| Component | Existing contract | Required extension |
| --- | --- | --- |
| `foreman/state.py` and recovery owner | Validated task/dispatch history and atomic state persistence. | An owner-managed task authority generation and explicit handoff, with schema/mixed-version migration documented beside the skill. |
| `foreman plan` / `foreman apply` | Plan selects seats without dispatch; apply validates task, requirements, correction bounds, brief/report paths, and native transport identity. Stable `--dispatch-id` supports recorded retries. | Task-scoped executor admission; authority checked inside each mutating owner transaction. A daemon must not call an unrestricted CLI with a forged environment. |
| `supervision.py` / `supervision_runtime.py` | Durable native enrollment and observations; exact bound foreman identity; reading/draining does not acknowledge an event. The current watcher is foreground and observational. | Service identity and verified handoff; task-filtered event consumption. Preserve explicit global operator holds; add task-local holds without releasing unrelated obligations. |
| `foreman check-member` / `foreman close-member` | Probe report/native evidence; close only after an assessed ledger outcome. | Structured profile-specific assessment and durable transition receipts. Unknown probe results stay unknown. |
| `foreman-queue` | Derives waiting seats; intentionally leaves gating, release, and closure to the foreman. | Replace its routine scheduling role after the executor is validated. Do not run two queues that both dispatch. |
| Generic coding-policy release bundle | Owns PR review, merge, immutable publication, moderation, and artifact confirmation. | An executor adapter that invokes those contracts and records exact observed outcomes. Never infer success from a zero-output or failed command. |
| Decision packet owner | Current `load-set` returns an evidence floor with broad historical reads. | Versioned bounded pending decisions, evidence pointers, invalidation rules, and targeted retrieval; amend mandatory-read floors explicitly. |

New progression state belongs to `herdr-foreman`, with one documented writer, schema version, reader contract, migration, and lock order. It references existing evidence rather than copying full reports or creating a parallel source of truth. Live sources are revalidated before an effect.

## Exceptions, recovery, and effect boundaries

- Before sending, persist intent and frozen assignment identity. After sending, record observed delivery. A crash or timeout between them produces an uncertain intent. Restart reconciles the actual native assignment/session before retrying; lease expiry alone never proves no send.
- Duplicate and late events cannot resolve another assignment or release its seat. Competing executor instances are fenced inside owner mutations. A stopped service preserves pending work; a replacement verifies the old process and authority rather than trusting a stale heartbeat.
- Approval binds the actual reviewer, assignment, relevant changes, and required check context. Task-keyed empty markers, commit subjects, and raw patch text are insufficient. Relevant changes invalidate approval. Rebase equivalence needs an explicit tested content-equivalence contract; it is not inferred from a familiar task ID.
- Unknown evidence creates a bounded packet naming the task, authority generation, head, unresolved obligations, source pointers, and permitted next actions. Its count/byte limits must fail to targeted retrieval rather than silently truncate findings.
- A task-local policy or dependency hold affects its dependency closure. An explicit global operator hold remains global until its owner releases it. The existing live hold is not changed by this decision.
- Production effects require target identity, an inspectable plan, destructive-effect classification, acceptance/readback probes, and recovery evidence appropriate to the operation. A passing fake client cannot establish safe live production execution.
- No review-round cap permits self-approval or bypass of a blocking policy finding. Exhaustion creates a decision packet. This resolves the conflicting two-round escalation and three-round self-review instructions in Drover by adopting neither permission.

## Delivery order and proof

1. Confirm the extracted packages and migrate consumers without rotating existing authority implicitly.
2. Establish the normalized baseline and preregister the ten-task comparison, including blocked/failed tasks and unknown effort. Baseline branch fixtures do not reproduce missing historical exports.
3. Implement outcome/risk profiles, task authority/handoff, and a process-independent executor with real owner/transport contract tests. Fault-inject crashes before/after durable intent, sends, observation, assessment, and release effects.
4. Implement bounded decision packets, effect/recovery checks, outcome/queue/effort telemetry, and integration backpressure. Record why each otherwise eligible task was excluded. Choose limits from measured congestion rather than copying Drover's WIP constants.
5. Run the real pilot under verified authorization. Compare completion-to-next-action delay and coordination time/output per accepted outcome alongside defects, rework, and production effects. Retire replaced choreography only after those results support it.

The schema-2 implementation now supplies native implementation/verification,
routine correction, full native release ownership, independent publication
readback, local cleanup and process-owned Stop continuation for supported new
tasks. Its isolated owner/kernel/Git fixtures do not prove a live team handoff
or ROI. Specialist/production adapters, actual consumer migration, retention,
telemetry/backpressure and the preregistered comparison remain separate epic
acceptance evidence. Issue #5 is not closed by this source description.

## Reproducibility and upstream license

Inspect the pinned checkout's `bin/fleet-watch`, `bin/fleet-batch-land`, `lib/fleet_dispatch.py`, `docs/OPERATING-MODEL.md`, and `docs/agent-land-loop.md`. The batch-landing suite uses temporary bare origins/worktrees and deterministic gates; the dispatch suite uses fixture boards. Reproduction commands are `bash tests/fleet-batch-land.test.sh` and `python3 tests/fleet_dispatch_test.py`, with `DROVER_CONFIG` pointing to an absent private config and `DROVER_HOME` to private scratch state. On this date, the unmodified batch suite passed 164 assertions across 37 scenarios and the dispatch suite passed 13 tests. These demonstrate upstream mechanisms, not our adapter or comparative delivery performance. Never run upstream mutating watcher/dispatcher commands against an operator fleet as an evaluation fixture.

Drover is MIT licensed, copyright 2026 drover contributors. This decision copies no upstream implementation. Any later reused substantial source must retain its license notice and identify the pinned origin and local adaptation.
