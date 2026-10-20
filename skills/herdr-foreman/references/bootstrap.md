# Herdr Bootstrap

## Scope

- This rule governs script lookup in Herdr skill command blocks.
- Follow the generic coding-policy script requirements after lookup.

## Installed Skill Lookup

- Narrow exception for installed Herdr skill lookup in Bash command blocks.
- Applies to `skills/herdr-foreman/SKILL.md`, `skills/herdr-standup/SKILL.md`, and their `references/*.md`.
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

## Role Context Reader

- `role-context` accepts the existing `--state`, `--config` and `--herdr-bin` overrides; use only the current owner's selected values.
- Success returns schema 1 with `role`, `verified`, `reason`, `context`, `reference` and `state_path`; every authority field is false.
- Foreman selection verifies the current native binding and discovery generation, or the configured first-launch seat and exact foreground argv. A trusted remote bound client instead uses its actual owner preflight.
- Worker selection requires its exact active native enrollment; a role hint alone establishes none.
- Known outages, changed ownership and operator holds retain a recovery capsule. Unverified sessions receive no foreman contract.
- Ordinary native sessions with `HERDR_ENV` unset read no owner or controller.
- Each co-shipped capsule is at most 4096 UTF-8 bytes; structured stdout is at most 16 KiB. Missing, unreadable or oversized contracts fail visibly without partial instructions.
- This reader creates no binding, task authority, admission, report, acknowledgement or dispatch.
- The shared SessionStart hook accepts at most 16 KiB of native JSON, verifies session identity and preserves the consumer cwd.
- Claude Code, Codex and Grok-compatible hooks use `hookSpecificOutput.additionalContext`; Cursor uses `additional_context`; portable Tessl uses `additionalContext`.
- Portable startup defers to registered Claude Code and Codex native hooks. Ordinary-session wrappers exit before runtime prerequisites.
- Context injection never removes instructions already loaded. Existing work retains its actual handoff, hold and Stop requirements.
