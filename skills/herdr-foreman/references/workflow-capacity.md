# Native Workflow Capacity

Read when selecting or changing capacity configuration before native task admission.

Config schema 9 can opt this schema-2 executor into `backpressure`. Select limits
from measured queue pressure and record the trial rationale before admission.
There are no default capacity limits. Existing configs without this declaration
retain their behavior. This policy governs native task admission; legacy rounds
retain their existing dispatch contract.

The captured config declaration has this shape; these numbers are fixture
examples for the wire format:

```json
{
  "schema_version": 9,
  "backpressure": {
    "schema_version": 1,
    "global": {"in_flight": 2, "integration": 1},
    "repositories": {
      "example/project": {"in_flight": 1, "integration": 1}
    },
    "exceptions": [],
    "rationale": "Replace with the measured congestion and selected trial limits."
  }
}
```

Keep the existing worker-kind and other config fields. Each positive signed-64-bit threshold
pauses new starts when its count reaches that value. Repository keys are exact
GitHub identities, independent of letter case. `in_flight` counts distinct
unfinished tasks with active enrollments, dispatch reservations, uncertain
delivery or recorded work. Duplicate assignments consume one task slot. A
closure releases settled work; an active enrollment or unsettled dispatch still
counts. Ambiguous closure evidence also remains counted. `integration` counts verification, correction and release work from the
same owners. Unknown repository binding is reported rather than guessed when a
repository limit needs it.

The executor checks capacity under the existing primary owner lock before
preparing the initial native job. Its canonical dispatch reservation becomes
visible in that transaction. It writes no separate capacity record. Existing
work remains eligible to verify, correct, release and reconcile; capacity never
waives task authority, operator holds, native provenance, quotas or review gates.
It neither searches for work nor fills idle seats for their own sake.

A task-specific exception contains `task`, timezone-aware ISO-8601 `until` and
bounded `reason`. It changes only the capacity decision. Expired exceptions
remain visible in a waiting result and permit no new start. Prepare these inputs
before admission; preserve captured inputs for in-flight work when selecting a
later configuration revision.

`progression-run` includes `data.capacity` for a configured new-job decision.
Its schema-1 summary names `allowed`, one primary `reason`, additional
`conditions`, global/repository `counts`, selected `limits`, any applicable
`exception`, and bounded `blocking_tasks` references with total/omitted counts.
Repository counts are null when no family check was needed; they are not measured zeros.
A capacity wait has `wake_agent: false` and creates no native intent. Unexamined
references remain counted. The result grants no progression or release authority.
The parser, task accounting and reference bounds are owned by
`skills/herdr-foreman/foreman/workflow_capacity.py`.
