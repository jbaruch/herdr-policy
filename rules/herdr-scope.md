---
alwaysApply: true
description: Minimal Herdr role routing, delegation boundary and installed lookup
---

# Herdr Scope

## Role Routing

- Ordinary work follows the project's coding policy; load no additional Herdr references.
- For an explicit Herdr request, use `Skill(skill: "herdr-foreman")`.
- The shared bootstrap verifies the actual launched role before selecting coordination context.
- `HERDR_ENV` is a routing hint, never role or task authority.
- Foremen load their operating contract and the references needed for the current decision.
- Workers load their verified assignment and worker protocol; never the foreman workflow.
- Preserve unresolved ownership, unknown deliveries and operator holds through outages and handoffs.
- Planning records and context selection grant no runtime or production authority.

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
