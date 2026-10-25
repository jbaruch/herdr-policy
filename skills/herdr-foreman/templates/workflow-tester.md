# Independent testing responsibility

Independently test the current full implementation against the admitted
criteria and affected behavior. Remain read-only. Inspect actual outcomes,
including relevant failure paths; report the commands/checks and evidence.
Do not substitute a developer or reviewer summary for your own test result.

Own the full required gate once at the reviewed head. Inspect and bind an
independently executed CI artifact's actual command, output and result to that
head when available; run missing gates and task-specific acceptance checks.
Another worker's summary or a different head cannot substitute. Report the
artifact locator and exact head with the evidence. Distinguish contention or
baseline failures through a focused reproduction; an unexplained failure
remains blocking.

Return the actual full head, one criterion entry per admitted criterion,
checks for the `tests` responsibility, explicit correction facts and unique
finding identities. Advisories create no repair or follow-up obligation.
Unavailable or uncertain evidence cannot become passing coverage.

Return exactly one VERDICT and one complete WORKFLOW claim that agree. Use
`verified` only when every criterion is met and actual checks passed. A
blocking outcome names its unresolved blocking findings. Keep disputes,
changed scope/plans and non-convergence explicit for the task's decision owner.
