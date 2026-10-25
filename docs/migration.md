# Extracted Pair Migration

## Compatible Versions

The reduced general package starts at coding-policy 0.4.0. Select a confirmed
Herdr release providing the required capabilities instead of pinning every
consumer to the first extraction. Coding-policy 0.3.407 is the last published
combined version. Never activate its team hooks alongside the extracted package.
Confirm each channel independently before changing a consumer's dependencies;
source documentation alone does not prove a version is published or installable.

| Required capability | First supporting release |
| --- | --- |
| Standalone general policy without Herdr runtime | coding-policy 0.4.0 |
| Extracted legacy coordinator and team hooks | herdr-policy 0.2.0 |
| Verified per-adapter ACR native policy identity | herdr-policy 0.3.2 |
| Explicitly admitted schema-2 task execution | herdr-policy 0.4.0 |
| Byte-bounded context views with CLI view schema 2 | herdr-policy 0.5.0 |
| Opt-in native new-start capacity limits using config schema 9 | herdr-policy 0.6.0 |
| Private native artifact retirement after verified acceptance | herdr-policy 0.6.1 |
| Task releases with independent Codex policy and Claude quality gates | herdr-policy 0.13.0 with coding-policy 0.5.0 |

These are capability floors, not a promise that an older owner can read newer
stored state. Record the actual installed pair and policy identity. Before using
the context views, update callers to consume their schema, pagination and omitted
evidence flags. Persisted owner formats retain their separate compatibility rules.

Herdr 0.13.0 requires the coding-policy 0.5.0 release bundle for schema-2 task
admission and progression. Update the selected consumer installation before
admitting new work. Existing tasks retain their recorded authority and holds;
use the owning upgrade/handoff procedure before resuming under a changed policy.
Generic cleanup of older extracted installations remains available.

Herdr policy lookup refuses legacy combined team trees in the project, global
Tessl installation or executing package's Tessl peer. An explicit helper root
does not bypass that check. Keep teams stopped and reconcile their existing
work before upgrading those installations.

One safety correction changes standup asking: the extracted entrypoint never
sends an unguarded prompt. Herdr 0.9.2's protocol-22 prompt request has no atomic
readiness condition. Ready, sufficiently wide workers receive an explicit exit-5
refusal and the skill fills their rows from the round log. Existing report
rendering remains available; this release does not claim an atomic prompt API.
Transport traces and errors also withhold operands and server prose, retaining
static operation metadata and recognized recovery codes.

## Prepare

Record the installed versions, managed native files and hooks, the active coordinator identity, selected task/stage, pending deliveries, holds and recovery obligations. Preserve the ledger, reports, supervision store, receipts and operator-owned configuration. Review installed outputs, not just source manifests.

Drain or reconcile workers through their existing owners. Keep operator holds in force. Stop the old coordinator before replacing hooks or policy. An unclassified or unknown delivery stays unresolved; do not clear it to make the upgrade proceed. Remote receipts have no automatic rotation transaction, so leave remote execution disabled until a verified new attachment is available.

## Update

For standalone consumers, update coding-policy only and remove stale team-owned managed outputs through the installing channel. Native user configuration, task records and evidence are not cleanup targets. Check startup, prompt submission and Stop without Herdr or team-only tools.

For team consumers, install the extracted Herdr package while the old coordinator remains stopped, update to reduced coding-policy, and realize both packages. Confirm that only the selected Herdr reset, supervision and startup hooks remain. Inspect installed versions and load the selected policy index, release skill and team-operation reference from their resolved paths.

Read back one coordinator identity and its owner records before any resume. Reconcile stored absolute references with the owning migration procedure; never rewrite frozen reports or enrolled brief bytes in place. Resume only after the operator's existing authority and holds permit it. A successful install does not authorize worker dispatch or production effects.

## Verify and Roll Back

Exercise fresh install, repeated realization, update and removal in disposable consumers first. Preserve a user-owned instruction sentinel and native setting through every operation. Verify standalone code has no Herdr imports and that the team hook owners retain their native failure contracts.

If the pair cannot be verified, keep the coordinator stopped. Use each consumer's
recorded previous versions and verify their availability through the same channel.
Restore channel-owned outputs together while preserving user files and all
state/evidence. Earlier extracted releases are rollback candidates only when
their owners support the current stored formats and obligations; the initial
extraction had no older extracted ACR pair.

A package rollback cannot rewind committed dispatches, migrations or other
native effects. Do not restore an earlier state snapshot over those effects.
If the previous owner cannot read current state, retain a compatible owner to
reconcile it while the team stays stopped. Never invent a rollback tag, move a
published tag, erase a receipt or start a competing coordinator. Record installed
versions, hook behavior and rollback outcomes in the migration issue.

The [recorded standalone Tessl/Codex trial](https://github.com/jbaruch/herdr-policy/issues/25#issuecomment-6269665180)
verified 0.3.274 → 0.4.0, repeat installation and rollback with user configuration
and owner/report fixture bytes preserved. It is disposable-consumer evidence;
actual adoption and the verified single-owner handoff remain under
[#25](https://github.com/jbaruch/herdr-policy/issues/25).
