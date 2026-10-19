---
alwaysApply: true
description: Applicability and installation boundary of the Herdr policy package
---

# Herdr Scope

## Applicability

- Apply this package to Herdr-managed team work.
- Standalone work follows the project's coding policy and any explicitly applicable delegation restrictions.
- Planning issues grant no runtime or production authority.

## Package Boundary

- This package owns the foreman, worker protocol, team state, native reset and supervision hooks.
- General release, review and worktree hygiene contracts belong to `jbaruch/coding-policy`.
- Install the compatible coding-policy package before team work; resolve one complete release bundle.
- Do not run the old coding-policy team hooks alongside this package's hooks.
- Preserve task records, reports, owner receipts and operator holds during migration.
- A policy change requires a verified authority handoff before an existing team resumes.
