# Native Workflow Capacity

Read when selecting capacity configuration before native task admission or inspecting current readiness.

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

## Readiness view

Invoke the foreman skill's `workflow-readiness` command to inspect open canonical
tasks. Optional `--task` selects one known open task; `--limit` and `--offset`
select a page. The default is ten tasks, with at most fifty examined per call.
The caller may supply a timezone-aware `--now` for a reproducible observation.
An unknown or completed selector refuses instead of returning an empty success.

The view shares the executor's current-input, prerequisite, capacity and worker
selection checks. It reads captured policy/contract/configuration, current Git
state and byte-bound prerequisite reports. Native identity is verified from
the actual controller only when native context is present. A positive
`dispatchable` observation also requires the actual executor's healthy current
process and kernel lease, and fresh positive observed headroom. Missing proof
remains unmeasured. Offline inspection contacts no native controller.

Each item has independent `ready` and `dispatchable` values, each a boolean or
null, and one named `reason`. `ready` means a next worker responsibility has
verified preparatory inputs. Capacity or known quota exhaustion can exclude
otherwise ready work; missing measurement, native identity or executor proof
leaves dispatchability null. Unadmitted tasks have unmeasured readiness. Current
jobs, pending intents, holds and task exceptions are not spare dispatch slots.
`enrollment_owner_unverified` identifies an excluded task; the canonical ownership
check is `has_unowned_enrollments` in `skills/herdr-foreman/foreman/progression_owner.py`.
Merge/publication/cleanup require their existing release readback; this view
does not substitute for it or for the legacy foreman queue.

`counts_scope` is `returned_items`. Within that page:

- Returned items equal `ready + not_ready + readiness_unmeasured`.
- Ready items equal `dispatchable + excluded_ready + dispatchability_unmeasured_ready`.
- `pagination` reports total, returned, omitted and the next offset.
- `unexamined_in_response` retains every open task outside the returned page.
- `context_complete` covers only the canonical task set selected for this response.

Output uses context-view schema 2 and at most 16 KiB of formatted JSON, including
its final newline. Pages shrink to fit; records are never truncated. Counts on
a partial page cannot establish that the whole factory has no ready work.
There is no saved readiness board, lease claim, plan write or dispatch effect.
The view is a current observation, never a reservation or permission to send.
Execution rechecks its real inputs, ownership and effect gates.

Native workflow planning excludes known exhausted worker kinds and retains
other eligible providers. Generated native aliases are not operator exclusions
against a worker-kind roster; assignment/session independence remains binding
at native execution. A recorded plan cannot bypass known exhaustion during
job preparation or native launch. Unknown headroom retains the planner's
existing selection behavior, while readiness reports it as unmeasured.
