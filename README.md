# jbaruch/herdr-policy

[![tessl](https://img.shields.io/endpoint?url=https%3A%2F%2Fapi.tessl.io%2Fv1%2Fbadges%2Fjbaruch%2Fherdr-policy)](https://tessl.io/registry/jbaruch/herdr-policy)

Herdr team coordination policy, distributed from the same authored files through Tessl and the Agentic Context Registry (ACR).

## Contents

The `herdr-foreman` skill owns dispatch, identity, reports, supervision, state and recovery. The `herdr-standup` skill asks idle workers for a bounded status update. Team rules, templates and the native reset, Stop and startup hooks ship with those skills.

General coding and release policy belongs to [jbaruch/coding-policy](https://github.com/jbaruch/coding-policy). Tests and fixtures remain in this repository under `tests/`; consumers do not install them. Extraction does not itself reduce model coordination cost. Background progression and context changes are tracked separately in [the epic](https://github.com/jbaruch/herdr-policy/issues/1).

| Rule | Purpose |
| --- | --- |
| [herdr-scope](rules/herdr-scope.md) | Team applicability and package boundary |
| [agent-team-operation](rules/agent-team-operation.md) | Existing team modes, delegation and foreman authority |
| [herdr-bootstrap](rules/herdr-bootstrap.md) | Installed skill lookup across both channels |
| [coding-policy-integration](rules/coding-policy-integration.md) | Team-specific exceptions and release integration |

| Skill | Purpose |
| --- | --- |
| [herdr-foreman](skills/herdr-foreman/SKILL.md) | Dispatch, supervise and accept team work |
| [herdr-standup](skills/herdr-standup/SKILL.md) | Collect bounded status from idle workers |

## Installation

Use a compatible extracted pair: herdr-policy **0.2.0** with the reduced coding-policy **0.4.0**. Do not combine this package's team hooks with coding-policy 0.3.x team hooks. Keep running teams stopped during cutover, preserve their records, and follow [the migration procedure](docs/migration.md).

```sh
tessl install jbaruch/coding-policy@0.4.0
tessl install jbaruch/herdr-policy@0.2.0
```

```sh
acr install github:jbaruch/coding-policy@0.4.0
acr install github:jbaruch/herdr-policy@0.2.0
acr realize
```

Each command requires that channel's confirmed publication. [#16](https://github.com/jbaruch/herdr-policy/issues/16) tracks Herdr publication, and [#17](https://github.com/jbaruch/herdr-policy/issues/17) tracks the compatible coding-policy release. A repository version alone is not publication evidence.

Tessl uses `.tessl-plugin/plugin.json`; ACR uses `agent-plugin.yaml`. ACR v1 has no package dependency declaration, so install both explicitly. The runtime resolves one complete coding-policy release bundle and fails on an incomplete selection. An optional absolute `HERDR_CODING_POLICY_ROOT` selects a source/package root exclusively; see [.env.example](.env.example).

## Supported Execution

Native Claude Code and Codex use direct reset, Stop and SessionStart hooks. ACR also realizes Cursor's canonical hook surface; installation and lifecycle behavior are covered by conformance checks. Grok uses the Claude-compatible settings contract; the reset and Stop subprocess regression tests preserve its shell-command form. Portable Tessl startup reports cache maintenance from a dry run and defers to the registered native startup hooks.

Remote controllers retain their policy-digest, lease and owner-receipt contract in [remote-context.md](skills/herdr-foreman/references/remote-context.md). This extraction does not add receipt rotation: a policy upgrade requires an explicit verified reattachment, and existing remote deployment remains disabled until that authority is established. Do not erase owner stores to bypass a mismatch.

## Development

Use Python 3.11+, Bash, Git, jq, Shellcheck 0.11.0 and Pyright 1.1.414. Check out the compatible coding-policy source for shared-helper integration tests; it is a development dependency, never vendored into this plugin.

```sh
HERDR_CODING_POLICY_ROOT=/absolute/path/to/coding-policy python3 scripts/run-tests.py
python3 scripts/run-diagnostics.py
tessl plugin lint .
acr validate . --json
```

The runner executes each Python and Bash suite separately with private XDG state. Tests import the canonical `skills/` sources without adding those paths to runtime subprocess environments. Select individual suites by passing their repository-relative paths. CI installs the published relocation baseline outside the checkout and pins the ACR validator. It gates actual native installation and canonical Tessl skill review at 85%. The scoped publisher credential is configured in [repository Actions secrets](https://github.com/jbaruch/herdr-policy/settings/secrets/actions); its creation and renewal are documented in `.env.example`. Source package manifests share one explicit version.

See [CHANGELOG.md](CHANGELOG.md) for release history and [migration.md](docs/migration.md) for cutover and rollback.

The serialized publish workflow runs the gates once, publishes the explicit Tessl version, then creates the immutable ACR tag and asset in a dependent job. Each channel is confirmed separately; Tessl moderation must pass before consumer adoption. If only ACR fails, rerun failed jobs on that same run, preserving the successful Tessl job and original baseline. Never move an existing tag or rerun a successful Tessl publish to repair the other channel. This repository records dated changelog headings manually and does not add a stamp commit during publication.
