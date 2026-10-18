# Extracted Pair Migration

## Compatible Versions

The target pair is coding-policy 0.4.0 and herdr-policy 0.2.0. Coding-policy 0.3.406 is the last monolithic reference used for extraction. Never activate both versions' team hooks together. Confirm each channel independently before changing a consumer's declared dependencies.

## Prepare

Record the installed versions, managed native files and hooks, the active coordinator identity, selected task/stage, pending deliveries, holds and recovery obligations. Preserve the ledger, reports, supervision store, receipts and operator-owned configuration. Review installed outputs, not just source manifests.

Drain or reconcile workers through their existing owners. Keep operator holds in force. Stop the old coordinator before replacing hooks or policy. An unclassified or unknown delivery stays unresolved; do not clear it to make the upgrade proceed. Remote receipts have no automatic rotation transaction, so leave remote execution disabled until a verified new attachment is available.

## Update

For standalone consumers, update coding-policy only and remove stale team-owned managed outputs through the installing channel. Native user configuration, task records and evidence are not cleanup targets. Check startup, prompt submission and Stop without Herdr or team-only tools.

For team consumers, install the extracted Herdr package while the old coordinator remains stopped, update to reduced coding-policy, and realize both packages. Confirm that only the selected Herdr reset, supervision and startup hooks remain. Inspect installed versions and load the selected policy index, release skill and team-operation reference from their resolved paths.

Read back one coordinator identity and its owner records before any resume. Reconcile stored absolute references with the owning migration procedure; never rewrite frozen reports or enrolled brief bytes in place. Resume only after the operator's existing authority and holds permit it. A successful install does not authorize worker dispatch or production effects.

## Verify and Roll Back

Exercise fresh install, repeated realization, update and removal in disposable consumers first. Preserve a user-owned instruction sentinel and native setting through every operation. Verify standalone code has no Herdr imports and that the team hook owners retain their native failure contracts.

If the pair cannot be verified, keep the coordinator stopped. Restore the recorded previous package versions and channel-owned outputs together, preserving user files and all state/evidence. The source baseline is coding-policy 0.3.406; verify its actual availability before rollback. Never move a published tag, erase a receipt, or start a second coordinator to recover. Record each channel's installed version and outcome in the migration issue.
