---
alwaysApply: true
description: Minimal Herdr role routing, delegation boundary and installed lookup
---

# Herdr Scope

## Role Routing

- Ordinary work follows general coding policy; load no Herdr references.
- Herdr standups and worker status updates use `Skill(skill: "herdr-standup")`.
- Other explicit Herdr requests use `Skill(skill: "herdr-foreman")`.
- Verify the launched role through the shared bootstrap.
- `HERDR_ENV` grants no role or task authority.
- Foremen load their operating contract and current decision references.
- Workers load their verified assignment and protocol; never the foreman workflow.
- Preserve ownership, unknown deliveries and holds across outages and handoffs.
- Planning and context selection grant no runtime authority.

## Delegation

- Authorized delegation uses existing Herdr owners; native subagent mechanisms are forbidden.
- An unavailable Herdr route grants no native fallback or new role authority.
- Standalone agents retain direct task ownership and applicable delegation restrictions.

## Installed Lookup

- Narrow exception for installed Herdr skill lookup in its command blocks.
- Applies to explicit Herdr skill commands in Tessl, ACR and source checkouts.
- Preconditions are binding: read `skills/herdr-foreman/references/bootstrap.md` Installed Skill Lookup before executing those blocks.
- Every other command block follows generic coding-policy script delegation.
- General review, release and worktree hygiene belong to `jbaruch/coding-policy`.
- Keep both packages' hooks distinct; a policy upgrade requires a verified authority handoff for existing work.

## Artifact Stdout

- Narrow exception for `skills/herdr-foreman/review-package.sh` artifact-path stdout.
- Applies to a completed Herdr review package in this installed plugin or its verified source.
- Preconditions are binding: read `skills/herdr-foreman/references/coding-policy-integration.md` Script Output before relying on it.
- Inputs: recorded `BASE HEAD [OUTFILE]` in the target checkout; absent `OUTFILE` uses `FOREMAN_REPORTS_DIR`.
- Success: absolute artifact path and newline. Failure: no path, nonzero exit, actionable stderr diagnostic.
- Every other script retains generic JSON stdout.
