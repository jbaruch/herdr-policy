# Outcome ownership and verification profiles

The pure profile decisions live in `foreman/workflow_profiles.py`. The
schema-2 task executor applies supported decisions through the existing native
owners after explicit admission. Existing rounds retain the current team
contract until their verified owner acts. Installation alone starts no service,
migrates no team and resumes no operator hold. The binding runtime contract is
`skills/herdr-foreman/references/task-workflow.md`.

One outcome owner keeps implementation and bounded corrections together and
coordinates verification and release. The progression service routes
permitted transitions; the operator or recorded task acceptance contract owns
acceptance. Neither the implementer nor a scheduler can self-approve work.
Generic coding-policy PR, review, CI and publication gates still apply.

| Profile | Eligibility | Independent verification |
| --- | --- | --- |
| Bounded | Known cause, bounded scope, reversible; no production effect, data migration, security boundary, cross-repository change or unfamiliar domain | One verifier supplies both code review and test evidence. |
| Complex | Broader scope, unsettled cause, limited reversibility, cross-repository change or unfamiliar domain | Separate reviewer and tester, each independent of implementation and one another. |
| Sensitive | Production effects, persisted-data migration or security boundary changes | Separate reviewer and tester plus relevant domain expertise; affected data and production operations require an effect/recovery gate. |

Combining responsibilities removes a handoff for eligible work; it does not
prove lower cost or equal defect detection. The ten-task pilot must measure
that tradeoff before promotion. Native assignment/session evidence must prove
worker independence: different labels or role names are insufficient. A
specialist domain can be covered by a qualified independent verifier when its
recorded capability satisfies that domain; uncertain coverage requires a
separate specialist or an exception decision. The current executor supports
bounded and ordinary complex work. Required specialist coverage and sensitive
work produce an explicit exception before implementation; their adapters are
not implemented by merely selecting a profile.

Risk facts have no defaults. Missing facts, unsupported versions and unknown
values require targeted evidence or a bounded decision. Scope/risk changes
must be reassessed; a task cannot retain a cheaper profile after eligibility
changes. Admission binds the complete risk facts to the task's current scope,
immutable contract and authority generation. Actual canonical dispatch and
enrollment owners retain native worker/session evidence.

Settled blocking findings return to the same outcome owner without a new
task framing. Resolved findings remain in the evidence store. Advisory-only
feedback records acknowledgment and continues the required verification or
release path without an advisory repair/review round. Disputed material
findings, unsettled causes, changed scope/effect plans, contradictory or stale
evidence, repeated defects and non-convergence produce a task-local decision
packet. No round count permits self-approval or waives a blocking finding.

A task-local exception holds that task and its explicit dependents. Unrelated
admitted work continues. Explicit global operator holds remain global until
their recorded authority releases them. A profile proposal releases no hold.

Inputs and outputs use schema 1. The functions reject unsupported input
schemas, do not migrate records and never write owner state. Caller-supplied
finding classifications must come from current artifact-bound owner
assessments; report prose is not an assessment. Pure acceptance cases are in
`tests/test_workflow_profiles.py`; isolated owner/native/Git integration cases
are in `tests/herdr-foreman/tests/test_workflow_*.py`. They exercise progression,
fault recovery, release readback, cleanup and Stop without claiming live native
deployment or comparative ROI. The real preregistered pilot remains required.

The service's `foreman/process_lease.py` holds a kernel lock for an
explicit process lifetime. Real-process tests cover competing holders, exit,
fork inheritance, replaced paths and released capabilities. This lock is a
liveness primitive; it grants no task generation, handoff or dispatch authority.
An expired heartbeat or released lock never proves an uncertain send was absent.
The native/remote authority guards remain binding. No service is activated by
importing these functions or installing this package.
