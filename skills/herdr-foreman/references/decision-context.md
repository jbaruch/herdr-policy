# Aggregate decision context

`foreman load-set` returns view schema 3. Its current-task response and every
explicit evidence excerpt consume a shared allowance across invocations.
Changing the decision, evidence question, path or offset does not grant another
allowance for unchanged task facts. A second cap covers all counted reads in the
bound foreman session. Task-state changes do not refund that session's allowance;
compaction alone does not establish a new bound session. Unrelated task changes and watcher heartbeat
or pane-output changes do not refresh it.

The allowance follows the selected task's owner-state binding within the
supervision-bound foreman context. Its calculation belongs to `generation` and
`consume` in `skills/herdr-foreman/foreman/decision_budget.py`. Limit constants
are `DECISION_BYTES`, `FOREMAN_BYTES`, `MAX_TASKS`, `STORE_BYTES` and
`PRESENCE_BYTES` in that module.

## Output and recovery

The command retains the full selected decision packet or bounded evidence chunk
and adds `aggregate_budget`:

| Field | Meaning |
| --- | --- |
| `task_state_sha256` | Binding of the current task facts; never approval or source acceptance |
| `limit_bytes` | Aggregate allowance for this task-state binding |
| `previously_returned_bytes` | Successfully committed charges before this response |
| `available_bytes_before_response` | Allowance available before charging this response |
| `foreman_limit_bytes` | Allowance across counted reads in the bound foreman session |
| `foreman_previously_returned_bytes` | Committed session charge before this response |
| `foreman_available_bytes_before_response` | Session allowance before charging this response |

Charges count the actual formatted JSON and terminating newline, including the
budget receipt and JSON escaping. A committed charge remains spent if output
delivery fails afterward. No report body or excerpt is saved in the counter.

Exit 0 returns the complete selected response and its receipt on stdout.
Exit 1 returns a JSON diagnostic on stderr and no decision content on stdout.
An invalid invocation retains argparse's exit 2. Counter, response or aggregate
limits refuse without hiding obligations, truncating a decision packet, or
resetting spent allowance. Unread evidence and every unresolved gate remain
unresolved. Do not mark a full review complete from excerpts.

When allowance or counter capacity is exhausted, route the specific question
to its task owner or use the existing verified foreman reset/resume workflow in
`skills/herdr-foreman/references/working-memory.md`. Preserve current goals,
authority, holds, changed heads, unknown deliveries and unexamined evidence.
Do not delete counters, copy owner files to obtain new allowance, or replace
required evidence with an excerpt. A changed task-state binding or verified new
foreman context does not accept a task or clear a hold.

The command serializes its owner-state observation with the primary owner lock
and commits the charge under the counter lock before emitting content. A busy
transaction refuses; wait for that owner process rather than removing locks.
A failed counter read or write refuses; preserve the file and repair its owner
state rather than treating its allowance as unused.
Evidence reads refuse symlinks and nonregular files without waiting for FIFO writers or
reading devices while the primary owner lock is held.

Attested remote bindings use the validated remote owner identity, without
inventing a native session value. Remote continuation follows the host-runtime
contract in `skills/herdr-foreman/references/remote-context.md`; never reset its
thin terminal anchor. This allowance adds no receipt-rotation or remote reset
API. Preserve the counter and hold the controller when its existing host cannot
prove the required planned continuation.

## Counter schema

Owner and sole writer: `herdr-foreman`. Canonical location:
`<canonical-selected-state-path>.context.json`, with the existing owner lock at
that path plus `.lock`. The document and each task record use `schema_version: 1`.
The owner accepts that version. No older version has been published for migration.

| Document field | Shape |
| --- | --- |
| `schema_version` | Counter document version |
| `state_path` | Canonical selected operational state path |
| `foreman_sha256` | Binding of the supervision owner's current foreman identity |
| `returned_bytes` | Committed charge across all counted task states in this foreman session |
| `tasks` | Map from canonical task identity to its current counter record |

| Task record field | Shape |
| --- | --- |
| `schema_version` | Counter record version |
| `state_sha256` | Current task-state binding |
| `returned_bytes` | Committed aggregate printed-byte charge |
| `responses` | Count of committed successful responses |

The file is a private regular mode-0600 file owned by the current user. Linked,
foreign, corrupt, unsupported and oversized files refuse without being replaced.
Preserve it during task artifact cleanup.

The owner retains a separate fixed creation receipt at
`<canonical-selected-state-path>.context-presence.json`. Its schema 1 contains
`schema_version` and `state_path_sha256`, the canonical owner-location binding.
It has the same private-file requirements and shares the counter lock. It is
created after the charged counter commits and before any content is emitted;
it never appends history or changes on a task/context refresh.

A valid receipt with a missing counter refuses, preserving the receipt for
recovery of the original charged state. Losing only the receipt never refunds
an intact counter: the owner recreates the receipt after preserving its charges.
An interrupted first receipt creation likewise retries from the charged counter.
Corrupt, foreign or unsupported receipts refuse without replacement. Preserve
both files during cleanup; never discard them to obtain fresh allowance.
The existing `migrate-home` owner rebinds both the counter's location and the
receipt's location hash under its home guard and owner locks, preserving all
charges. An interrupted move refuses inconsistent reads; rerun that same
migration to finish its atomic identity rewrites without discarding either file.

Both files use the `jbaruch/coding-policy` `stateful-artifacts` gate-store exception:
unsupported readers refuse the context read with an update diagnostic. Other
readers never migrate, edit or discard the store. It grants no operational task
authority and changes no primary, recovery or supervision schema.

Lifecycle: retain one capped counter and its fixed creation receipt for the
selected owner location. Current
task records replace their prior binding in place; there is no revision archive,
timestamp series or report cache. A changed bound native foreman session replaces the prior session's counters.
Session metadata changes do not refund charges. Loss of a previously recorded
binding refuses; first binding carries prior offline charges. Capacity exhaustion preserves existing
records instead of evicting spent allowance. There is no manual reset command.

## Scope and rollout

This allowance covers `load-set` and its evidence reads. It does not count other
commands, policy reads, raw filesystem reads, GitHub responses, stderr, or model
input outside this API. It is not a global token meter or evidence of ROI.
Memory and supervision responses retain their separate per-response bounds;
aggregate coverage of those inputs remains work under issue #11.

Earlier Herdr releases do not enforce this allowance. Upgrade each foreman
reader before claiming aggregate coverage; view-schema or counter-file presence
does not make an older executable enforce the contract. The allowance remains
an observation/exposure control, never task acceptance or live migration proof.
