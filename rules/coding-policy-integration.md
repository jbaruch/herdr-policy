---
alwaysApply: true
description: Team-specific sync, isolation, release and cleanup contracts at the coding-policy boundary
---

# Coding Policy Integration

## Sync and Checkouts

- Applies only to a verified Herdr team round under `rules/agent-team-operation.md`.
- The foreman provisions each writer's worktree and records its fetched base.
- A worker consumes the provisioned base instead of fetching or rebasing the shared checkout under generic `sync-before-work`.
- Preconditions are binding: read `skills/herdr-foreman/references/team-operation.md` Writers and Checkouts before relying on that exception.
- The foreman owns worktree teardown and carries out operator decisions on shared checkout hygiene.
- Workers retain diagnostics and handoff obligations on their own changed files.

## Review and Release

- Advisory findings are acknowledged in the existing task report or round log; they create no follow-up or delivery prerequisite.
- The release worker reports blocking findings to the foreman and performs no source repair.
- Team weighing and pinned-judge verification follow `skills/herdr-foreman/references/release-integration.md`.
- Generic release gates and floors remain binding after team authority verification.

## Accepted Scope Exclusion

- Narrow exception for a Judge-Accepted Defect Carve-Out in a team fix loop that did not converge.
- Preconditions are required: the current exhaustion has a recorded `REMEDY: stop` diagnosis; the excluded defect has a tracked issue; the shipped scope excludes its work and carries no other blocking finding.
- CI, external review and independent reviewer/tester passes must hold on the shipped tip.
- The operator may override the stop by explicitly authorizing a plan over it.

## Script Output

- Narrow exception for `skills/herdr-foreman/review-package.sh` artifact-path stdout under generic script delegation.
- Success emits only the absolute completed package path and a newline; the package contains the resolved commit range, commit list, diff stat and patch.
- Failure emits no path, exits nonzero and gives an actionable stderr diagnostic.
- `tests/herdr-foreman/tests/test_review_package.py` verifies the contract.
