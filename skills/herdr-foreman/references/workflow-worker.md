# Admitted Workflow Worker Contract

Read the co-shipped `skills/herdr-foreman/references/worker-context.md` and the selected general policy, then
perform only the current admitted assignment and selected responsibilities.
The executor owns progression and local teardown. Review and testing are
read-only. A release worker follows its complete selected release skill and
binding references, preserves the writer checkout and repairs no source.
Do not read the foreman workflow or reconstruct prior rounds.

## Report schema

A report is the enrolled file delivered by the exact native assignment. The
final chat line is exactly `REPORT: <absolute path>`. File existence, pane text,
an exit code or a report's own claim is insufficient delivery proof. Native
launch, permissions, model/process, composer and final-source checks remain
binding. Their canonical assignment record owns tier provenance; repeating
that metadata in prose grants no extra authority.

Every report contains exactly one operative `WORKFLOW: <JSON object>` line,
outside examples, quotations, indentation and code fences. A reviewer/tester
also carries exactly one operative `VERDICT: approved|blocking` line. The
claim must match that verdict. The complete schema is validated by
`skills/herdr-foreman/foreman/workflow_contract.py`; unsupported, missing, duplicate or conflicting
claims do not advance the task.

The schema-1 claim fields are `schema_version`, `task`, `head_revision`,
`responsibilities`, `outcome`, `acceptance`, `checks`, `findings`, `correction`,
`pull_request`, `review_snapshot`, `review_evidence` and `publication`.

- Use the actual full Git head and selected responsibilities: `implementation`,
  `review`, `tests` or `release`. A bounded verifier supplies both `review` and
  `tests`.
- Each check carries `responsibility`, `name`, `result` and `evidence`. Results
  are `passed`, `failed` or `unavailable`. A successful outcome needs actual
  successful evidence for every selected responsibility.
- Independent verification addresses each admitted criterion in order with
  `criterion` (one-based number), `state` (`met` or `unmet`) and `evidence`.
  Other responsibilities set `acceptance` to null. A verified outcome requires
  every criterion met and every claimed check passed.
- Implementation outcomes are `built` or `blocked`; verification outcomes
  are `verified`, `blocking` or `blocked`. Release outcomes are `delivered`,
  `blocking` or `blocked`; `ready` records preparation only and cannot complete
  delivery.
- Findings carry schema 1, a unique `id`, `severity` (`blocking`, `advisory` or
  `uncertain`) and `status` (`open`, `resolved` or `disputed`). Review/test and
  blocking release outcomes supply explicit correction facts:
  `scope_unchanged`, `cause_settled`, `contradictory_evidence`, `repeated_defect`,
  `non_converged`, `changed_production_plan`. Other outcomes use an empty
  findings list and null correction. The executor derives current authority
  and evidence facts itself.
- PR/review/publication fields are null outside release. A delivered release
  provides the actual PR, complete pre-merge canonical watcher artifact
  receipt and all-body digest, plus the publication claim described below.

## Publication claim

The publication claim has schema 1, `baseline`, `baseline_at`, `publisher_run`,
`tag` and `tessl_version`. Report actual canonical-helper results. A Tessl
baseline/time must come from before the actual merge; preserve `unpublished`
only when its helper verified that sentinel. Nonselected channel fields are
null. No publication uses a null run id; a task without publications uses null
publication identities. The initial adapter supports the admitted
merge-triggered Tessl/ACR publisher, bound to workflow, merge commit, push and
base ref. Other publication/deployment adapters require their actual owner.


Preserve current report gates and operator holds before merge or publication.
Return blocking source corrections to implementation. Required publication,
deployment and acceptance need their actual evidence; merge alone is not
substituted. The role template supplies the current release procedure.
