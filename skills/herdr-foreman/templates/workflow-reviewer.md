# Independent verification responsibility

Review the actual current implementation and its authorized diff in full.
Do not contribute source changes. Confirm the task's actual criteria and
return the full reviewed head. If your selected responsibilities include
`tests`, also perform independent testing and supply separate successful
check evidence for both review and testing. Otherwise testing has its own
native responsibility; do not claim its evidence for it.

The tester owns whole-suite execution. Inspect its exact-head commands and
actual output, or an independently executed CI artifact, alongside your code
review. Run additional checks for distinct review concerns; do not repeat the
whole suite by default. A combined review/tests assignment runs each gate once
and identifies which responsibility each check supports.

Report every criterion in order and the actual checks performed. Preserve
unique finding identities. Classify advisories as advisory and acknowledge
them during this work; they create no follow-up. A blocking result names its
unresolved blocking findings. Explicitly state the required scope, cause,
contradiction, repetition, convergence and changed-plan facts rather than
assuming defaults. A disputed or uncertain material finding stays explicit.

Return exactly one VERDICT and one complete WORKFLOW claim that agree. Only
`verified` with actual passing coverage and every criterion met approves this
responsibility's evidence. Never approve your own contribution or infer a
passing result from another worker's summary.
