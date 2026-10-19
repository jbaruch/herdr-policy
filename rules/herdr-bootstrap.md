---
alwaysApply: false
applyTo: "skills/herdr-foreman/**, skills/herdr-standup/**, **/skills/** — when authoring or executing the named Herdr skill command blocks"
description: Installed Herdr skill lookup for Tessl, ACR native layouts and verified source clones
---

# Herdr Bootstrap

## Scope

- This rule governs script lookup in Herdr skill command blocks.
- Follow the generic coding-policy script requirements after lookup.

## Installed Skill Lookup

- Narrow exception for installed Herdr skill lookup in Bash command blocks.
- Applies to `skills/herdr-foreman/SKILL.md`, its `references/*.md`, and `skills/herdr-standup/SKILL.md`.
- Preconditions (all required):
  1. Initialize `HS` to `.tessl/plugins/jbaruch/herdr-policy/skills/herdr-foreman/` or the corresponding `herdr-standup/` path.
  2. Use one directory test for project-local lookup, one for `$HOME` fallback, and one whole-string origin `case` for source lookup.
  3. Accept only `git@github.com:jbaruch/herdr-policy`, `https://github.com/jbaruch/herdr-policy`, and `ssh://git@github.com/jbaruch/herdr-policy`, each with or without `.git`.
  4. Source lookup selects `skills/<same-skill>/`.
  5. Every other origin exits nonzero with an install instruction.
  6. Invoke only that skill's co-shipped scripts through quoted `$HS` paths with explicit interpreters.
  7. Repeat lookup in each independent command block.
  8. Lookup performs no writes, network requests, permission changes, sourcing or evaluation of repository code.
  9. ACR consumers use the renderer's owned native skill directories with the same trailing slash and lookup branches.
- Every other command block follows generic coding-policy script delegation.

## Verification

- `tests/test_skill_bootstrap.py` checks co-shipped targets, explicit interpreters, local/global precedence, source identities, impostor refusal, spaces and mode-0644 scripts.
- Recorded native fixtures do not replace actual ACR installation conformance.
- `scripts/check-installations.py` executes selectors extracted from installed Markdown and checks co-shipped targets on each claimed adapter.
