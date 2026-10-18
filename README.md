# jbaruch/herdr-policy

Herdr team coordination policy, distributed from the same authored files through Tessl and the Agentic Context Registry (ACR).

## Contents

The `herdr-foreman` skill owns dispatch, identity, reports, supervision, state and recovery. The `herdr-standup` skill asks idle workers for a bounded status update. Team rules, templates and the native reset, Stop and startup hooks ship with those skills.

General coding and release policy belongs to [jbaruch/coding-policy](https://github.com/jbaruch/coding-policy). Tests and fixtures remain in this repository under `tests/`; consumers do not install them. Extraction does not itself reduce model coordination cost. Background progression and context changes are tracked separately in [the epic](https://github.com/jbaruch/herdr-policy/issues/1).

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

The runner executes each Python and Bash suite separately with private XDG state. Tests import the canonical `skills/` sources without adding those paths to runtime subprocess environments. Select individual suites by passing their repository-relative paths. CI pins the coding-policy helper source and ACR validator; source package manifests share one explicit version.

See [CHANGELOG.md](CHANGELOG.md) for release history and [migration.md](docs/migration.md) for cutover and rollback.
