# Outcome ownership and verification profiles

This candidate policy is implemented by `foreman/workflow_profiles.py`. It
proposes responsibilities and correction routes without dispatching, accepting,
releasing, or authorizing effects. Existing rounds retain the current team
contract until an explicit admission and verified single-authority handoff
enables this workflow. Installing these functions is not that handoff.

One outcome owner keeps implementation and bounded corrections together and
coordinates verification and release. The progression service will route
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
separate specialist or an exception decision.

Risk facts have no defaults. Missing facts, unsupported versions and unknown
values require targeted evidence or a bounded decision. Scope/risk changes
must be reassessed; a task cannot retain a cheaper profile after eligibility
changes. The future admission owner must bind the profile and actual native
assignments to the task's current scope and authority generation.

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
assessments; report prose is not an assessment. Executable acceptance cases
are in `tests/test_workflow_profiles.py`. A verified service/admission adapter
and a comparative pilot remain required before runtime activation.
