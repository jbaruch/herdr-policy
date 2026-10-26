# Private Observer Storage

The `herdr-observer` runtime is the sole writer of its local cache. `Store` in
`skills/herdr-observer/factory_observer/store.py` owns migration 1 of
`observer.sqlite3`, identified by SQLite `user_version`. Every JSON record has
`schema_version: 1`. Unknown migrations/records are refused without rewriting.
No older observer schema exists. The cache supplies evidence and scheduling,
never delivery authority.
`Store` validates table/key-specific formats from `factory_observer/schema.py`
on every read and write. Partial receipts, malformed required fields and unknown
record kinds are refused without rewriting. Compatible extra fields survive.

The root is `herdr-observer` under `XDG_STATE_HOME`, falling back to
`~/.local/state`. The runtime requires owned directories and regular files,
refuses links, and restricts directory/file permissions. It creates no `.hr`
archive, repository output or public history. Retention, database ceiling and
report limits are owned by the constants in `store.py` (referenced from the
analysis contract); final reports are retained separately from rolling samples.
Expiry commits receipt deletion before a separate bounded file sweep. The sweep
holds the report-writer lock and removes only managed files lacking a committed
receipt; rollback cannot revive a receipt for an unlinked report. Interrupted
sweeps safely retry after restart. A file-backlog ceiling prevents accumulation
when cleanup fails, preserving the pending job for retry after storage recovery.
`collector.stderr` keeps one bounded private launch diagnostic and is replaced
on restart. The entrypoint owns its byte bound. Fatal diagnostics include the
exception type and stack locations, excluding exception values and local variables.

The migration creates these tables:

| Table | Key and value contract |
| --- | --- |
| `meta` | Named records: `binding` (exact native identity, agent name, cwd, registration time), `config` (enabled, collection start, selected owner paths, native binary), `current` (last sample, coverage, quota observations, anomaly continuity), `heartbeat` (service time/health), `pending` (one analysis job, frozen payload, reasons, original send status, last wake time, reconciliation and attention receipts), `schedule` (last analysis/weekly report and anomaly fingerprint), `closures` (bounded per-owner event sequence watermarks), `retention` (eviction counts/time and the coverage floor for evicted source baselines). |
| `sources` | Pane-independent native session key; byte cursor/file identity, current model/effort, numeric usage baseline, bounded tool/message hashes, coverage and source locator. Quota keys retain bounded observations with their original measurement/reset identities. No prompt, output or reasoning bodies. |
| `bins` | Identity, role/task and UTC hour key; sampled status duration, native counters/proxies, model/effort totals and source byte locators. No transcript bodies. |
| `reports` | Generated job ID; private report path, kind, time, content digest and generic notification result. |

Only this skill's CLI/collector writes these records. `status` and `evidence`
return last-seen data; `next`, `ack` and `report` require the registered live
observer. The shared SessionStart hook's
`skills/herdr-foreman/foreman/observer_role.py` reader accepts migration/record 1
read-only, reads only `binding` and `config` from this cache, and returns no role
for missing, incompatible or untrusted storage. It also checks current supervision
ownership through that owner's reader, including during foreman outages. Foreman
and worker contracts take precedence over observer registration. No reader here
migrates a store or clears ownership.

`meta.acknowledgements` retains bounded `jobs` receipts with `id` and `at` fields;
its limit is owned by `store.py`. Retrying a retained acknowledgement returns
success without clearing a newer job or advancing its schedule. An expired or
unknown job is refused without effects. Report retry receipts use `reports`.
The role reader requires the registered nonempty name to match the live pane.

The collector owns one service lock and continuously reads Herdr topology,
selected current owner metadata, existing quota snapshots and matching native
logs. Source readers and their accepted owner schemas are documented in
`sources.py`; they do not migrate those owners. Filename discovery is bounded;
unavailable native logs, quota and outcomes remain explicit gaps. Native source
files stay where their runtimes own them. No telemetry is uploaded.

Current owner metadata comes from the co-shipped read-only
`skills/herdr-foreman/observer-view.py`, backed by
`skills/herdr-foreman/foreman/observer_projection.py`. Its binding, current and
closure sections return byte-bounded pages with totals, omissions and continuation
offsets. The owner reads its own state; the observer receives current identity,
active assignment, quota and closure fields without historical briefs, reports or
hold evidence. Collector page limits remain explicit coverage gaps. Unsupported
owners and oversized projected rows have distinct private coverage diagnostics;
inspect the named section rather than increasing raw-history limits or replacing
the owner. This protocol creates no cache store, migration or delivery authority.
Binding receipt discovery excludes lock sidecars and deduplicates owners before
its owner limit. Separate directory and receipt-scan safety bounds retain
`factory_directory_scan_truncated` and `factory_receipt_scan_truncated` coverage
gaps respectively. Explicit selected owner paths remain usable without claiming
the registry was fully inspected.
`status` and fleet `evidence` expose `coverage_diagnostics` with the failed section,
refusal class and recovery action. A failed current or closure section retains
independently readable binding evidence; its counts and outcomes remain unknown.

A precheck emits `wake_agent` and `data`. It saves the same payload as one pending
job before waking only the exact registered idle observer. Wakes are coalesced
while the agent is busy. Persisted send intent preserves uncertainty after lost
responses or crashes; neither `sending` nor `unknown` proves a turn ran. Stale
jobs use journaled reconciliation and generic attention notifications. The
reconciliation asks the same verified idle observer to inspect the original job;
it repeats no factory work. Report/ack idempotency stays bound to that job ID.
Collection continues independently. The analysis contract points to the runtime's
cadence and bounds; recovery does not create a model polling loop.

The service commits age/count/byte-pressure eviction before new samples. It
preserves pending jobs, schedules and report receipts while trimming cached bins
and source projections. A source-baseline eviction advances the coverage floor;
a resumed session cannot re-charge its evicted history. Evidence and status show
retention exclusions. Merged, abandoned and unknown closure counters stay separate.
Closure watermarks refresh current owners before eviction. `meta.closures`
retains `evicted_through` as the history floor for missing owner baselines;
returning owners exclude older receipts and expose that exclusion as coverage.

Only the supplied private `draft_path` is used for report drafts. `report` saves
a bounded UTF-8 Markdown file under `reports/`, records its receipt before a
generic native notification, and is idempotent by job ID. Lost notification
responses are not automatically resent. Completed drafts are removed. `ack`
finishes an analysis without a report; it cannot replace a due weekly report.
Starting or stopping collection never changes foreman/worker records or holds.

Start this role when enabling factory observation. Its detached collector
survives agent turns and compactions, but does not install a login service or
restart the Herdr application after a machine reboot. Relaunch the observer with
the factory after reboot. `status` exposes a dead collector or missing reporter;
restart from the same observer to retain cursors and pending work. An explicitly
stopped role can be registered to a replacement session; uncertain pending work
is preserved for inspection rather than replayed.

## Inspect Observer Health

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-observer/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-observer/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/observer.sh" status
```

JSON distinguishes a running collector, source age, coverage, pending send status
and private report/diagnostic paths. If collection exits unexpectedly, inspect
the private diagnostic before repairing the installation/store and restarting.
Status is last-seen evidence, not proof of current native
identity. If the collector stopped, use Start Observation in the invoking skill
from the original observer to recover.
If a wake is uncertain, read `next` there; do not resend a native prompt. A
replacement requires an explicit stop before registering its own live identity.
Collection continues while the reporter is busy or missing. Finish here.


## Stop Observation

```bash
HS=.tessl/plugins/jbaruch/herdr-policy/skills/herdr-observer/; [ -d "$HS" ] || HS="$HOME/$HS"; [ -d "$HS" ] || case "$(git config --get remote.origin.url)" in git@github.com:jbaruch/herdr-policy|git@github.com:jbaruch/herdr-policy.git|https://github.com/jbaruch/herdr-policy|https://github.com/jbaruch/herdr-policy.git|ssh://git@github.com/jbaruch/herdr-policy|ssh://git@github.com/jbaruch/herdr-policy.git) HS=skills/herdr-observer/ ;; *) echo "herdr-policy skill not found: install jbaruch/herdr-policy" >&2; exit 1 ;; esac
bash "$HS/observer.sh" stop
```

This disables future collection and wakes without touching delivery owners or
private reports. Before replacing the role, inspect health until `running` is false.
Finish here.
