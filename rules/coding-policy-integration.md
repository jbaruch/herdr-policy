---
alwaysApply: false
applyTo: "** — during verified Herdr team rounds or when applying Herdr release, cleanup and script-output contracts"
description: Team-specific sync, isolation, release and cleanup contracts at the coding-policy boundary
---

# Coding Policy Integration

## Sync and Checkouts

- Applies only to a verified Herdr team round under `rules/agent-team-operation.md`.
- The foreman provisions each writer's worktree and records its fetched base.
- A worker consumes the provisioned base instead of fetching or rebasing the shared checkout under generic `sync-before-work`.
- Preconditions are binding: read `skills/herdr-foreman/references/team-operation.md` Writers and Checkouts before relying on that exception.
- The operator resolves listed shared-checkout items by push, commit, pull request or delete.
- The foreman carries out none of those resolutions.
- Foreman teardown is limited to the merged task's worktree under `skills/herdr-foreman/SKILL.md` Step 15 and its binding post-merge order.
- Workers retain diagnostics and handoff obligations on their own changed files.
- Narrow exception for the explicitly admitted schema-2 task executor.
- Applies only under its verified current service generation and the admission boundaries in `skills/herdr-foreman/references/task-workflow.md`.
- Preconditions are binding: read `skills/herdr-foreman/references/task-workflow.md` Ownership and current inputs and Process lifetime and cleanup before relying on it.
- Its isolated writer/base verification and fixed post-acceptance cleanup follow that contract instead of the legacy round's Writers and Checkouts and Step 15 paperwork.
- Native provenance, actual merged-head verification, preservation of unrelated work and generic release gates remain binding.
- Every other team round retains the legacy provisions above.

## Review and Release

- Advisory findings are acknowledged in the existing task report or round log; they create no follow-up or delivery prerequisite.
- The release worker reports blocking findings to the foreman and performs no source repair.
- Team weighing and pinned-judge verification follow `skills/herdr-foreman/references/release-integration.md`.
- Generic release gates and floors remain binding after team authority verification.

## Accepted Scope Exclusion

- Narrow exception for a Judge-Accepted Defect Carve-Out in a team fix loop that did not converge.
- Applies only to the excluded defect in the shipped team scope.
- Preconditions (all required):
  1. The current exhaustion has a recorded `REMEDY: stop` diagnosis.
  2. The excluded defect has a tracked issue.
  3. The shipped scope excludes that work and carries no other blocking finding.
  4. CI, external review and independent reviewer/tester passes hold on the shipped tip.
- The operator may override the stop by explicitly authorizing a plan over it.
- Every other blocking finding follows the generic review rule.

## Script Output

- Narrow exception for `skills/herdr-foreman/review-package.sh` artifact-path stdout under generic script delegation.
- Applies only to this script's completed review package.
- Preconditions (all required):
  1. Success emits only the absolute completed package path and a newline.
  2. The package contains the resolved commit range, commit list, diff stat and patch.
  3. Failure emits no path, exits nonzero and gives an actionable stderr diagnostic.
  4. `tests/herdr-foreman/tests/test_review_package.py` verifies the contract.
- Every other skill script retains the generic JSON-output requirement.
