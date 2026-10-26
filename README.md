# jbaruch/herdr-policy

[![tessl](https://img.shields.io/endpoint?url=https%3A%2F%2Fapi.tessl.io%2Fv1%2Fbadges%2Fjbaruch%2Fherdr-policy)](https://tessl.io/registry/jbaruch/herdr-policy)

Herdr team coordination policy, distributed from the same authored files through Tessl and the Agentic Context Registry (ACR).

## Contents

The `herdr-foreman` skill owns dispatch, identity, reports, supervision, state and recovery. The `herdr-standup` skill asks idle workers for a bounded status update. Role contracts, templates and the shared reset, Stop and startup hooks ship with those skills.

General coding and release policy belongs to [jbaruch/coding-policy](https://github.com/jbaruch/coding-policy). Tests and fixtures remain in this repository under `tests/`; consumers do not install them. Extraction does not itself reduce model coordination cost. Background progression and context changes are tracked separately in [the epic](https://github.com/jbaruch/herdr-policy/issues/1).

| Rule | Purpose |
| --- | --- |
| [herdr-scope](rules/herdr-scope.md) | Team applicability and package boundary |

| Skill | Purpose |
| --- | --- |
| [herdr-foreman](skills/herdr-foreman/SKILL.md) | Dispatch, supervise and accept team work |
| [herdr-standup](skills/herdr-standup/SKILL.md) | Collect bounded status from idle workers |
| [herdr-observer](skills/herdr-observer/SKILL.md) | Observe factory efficiency and produce private reports |
| [herdr-optimizer](skills/herdr-optimizer/SKILL.md) | Deliver simpler logic, remove redundancy and reduce evidenced waste |

The optimizer is a standing delivery specialty using ordinary developer
assignments. It finds and implements worthwhile simplifications in an authorized
area, alongside independent feature work, with normal review and tests. The
foreman continues useful slices without reserving a permanent model or pane.
An unchanged area with no worthwhile candidate needs no repeated scanning.

The observer uses a lightweight detached collector while its native agent sleeps
between analyses. It watches current factory topology, incremental native logs
and existing subscription measurements, then reports weekly or alerts sooner
when warranted. Conclusions cover coordination, parallel delivery, provider load,
model/effort suitability and other opportunities, with explicit coverage gaps.
Reports stay in private local storage; Herdr notifications contain no operational
details. It adds no delivery gate or worker reporting loop. Start the role in a
dedicated named Herdr agent through its skill; inspect its health after launch.
See [the private storage and recovery contract](skills/herdr-observer/references/storage.md).

## Bounded task context

Current owner views share the existing printed-byte allowance. Task-cost output
is paginated; GitHub evidence is retrieved by a named reference/question as one
index page or a content-hash-bound body chunk. Results retain unexamined coverage,
unknown costs and recovery obligations. History is not mirrored locally.
See [the context API contracts](skills/herdr-foreman/references/decision-context.md).
These limits are not measured throughput or token savings.

## Installation

Use a compatible extracted pair: herdr-policy **0.19.0** with coding-policy **0.5.0** or **0.5.1**. Do not combine this package's team hooks with coding-policy 0.3.x team hooks. Keep running teams stopped during cutover, preserve their records, and follow [the migration procedure](docs/migration.md).

Standup remains available from existing reports and the round log. The current
ask entrypoint inspects readiness and refuses prompting with exit 5: Herdr
0.9.2's API has no atomic readiness precondition. No standup input is sent until
a tested atomic adapter exists. Foreman task dispatch is separate from this
optional standup path.

```sh
tessl install jbaruch/coding-policy@latest
tessl install jbaruch/herdr-policy@latest
```

Native Antigravity subscription workers are available through the optional
[worker profile](skills/herdr-foreman/antigravity.example.json). Sign in with
`agy`, check that account's models/quota, and add the profile to the existing
config without replacing other providers. See [Antigravity setup and boundaries](skills/herdr-foreman/references/antigravity.md).

```sh
acr install github:jbaruch/coding-policy@latest
acr install github:jbaruch/herdr-policy@latest
acr realize
```

Each command requires that channel's confirmed publication. [#16](https://github.com/jbaruch/herdr-policy/issues/16) tracks Herdr publication, and [#17](https://github.com/jbaruch/herdr-policy/issues/17) tracks the compatible coding-policy release. A repository version alone is not publication evidence.

Tessl uses `.tessl-plugin/plugin.json`; ACR uses `agent-plugin.yaml`. ACR v1 has no package dependency declaration, so install both explicitly. The runtime resolves one complete coding-policy release bundle and fails on an incomplete selection. An optional absolute `HERDR_CODING_POLICY_ROOT` selects a source/package root exclusively; see [.env.example](.env.example).

## Supported Execution

Native Claude Code and Codex use direct reset, Stop and SessionStart hooks. ACR also realizes Cursor's canonical hook surface; installation and lifecycle behavior are covered by conformance checks. Grok uses the Claude-compatible settings contract; the reset and Stop subprocess regression tests preserve its shell-command form. Portable Tessl startup uses the same role reader and defers to the registered native hooks. All ordinary-session hooks return before checking Python, Herdr or owner files.

Requested Codex foreman resets also verify host-goal transfer through the existing
Codex app-server control socket. The successor retains the objective and remaining
budget; the outgoing goal executor is retired before continuation is admitted.
Use the selected `foreman-reset-status --stow <id>` receipt for recovery. Native
Claude/Grok resets create no external goal. See [reset integration and validation](skills/herdr-foreman/references/reset-hooks.md).

Only the small [routing rule](rules/herdr-scope.md) loads automatically. The
skill entrypoints route to decision-specific references. SessionStart verifies
the actual native session and existing owner/configured foreman seat before
loading a bounded foreman, worker or recovery capsule. A bare `HERDR_ENV` grants
no role. Known outages and holds preserve recovery obligations; changing context
never clears them. Hooks cannot remove text already loaded into a session. Custom owner/config
paths use the two explicit startup locators in the
[bootstrap contract](skills/herdr-foreman/references/bootstrap.md#selected-owner-paths);
managed workers receive the state locator through native workspace environment
settings. Existing foreman panes need their verified fresh bootstrap/handoff.

Foremen load the [team contract](skills/herdr-foreman/references/team-scope.md)
and [workflow](skills/herdr-foreman/references/foreman-workflow.md) only when
applicable. Workers get their assignment and
[worker protocol](skills/herdr-foreman/references/worker-context.md), plus the
[report schema](skills/herdr-foreman/references/workflow-worker.md) for admitted
workflows. They do not load foreman choreography. Reset and Stop retain their
existing owners. Startup does not enumerate history or run cache maintenance.
Cursor's hook format is supported; it does not add a native Herdr foreman kind.

Inspect current admitted-task readiness with the foreman skill's `workflow-readiness`
command. Its bounded pages distinguish dispatchable work, exclusions and unmeasured
proof. Read [the view contract](skills/herdr-foreman/references/workflow-capacity.md#readiness-view)
before interpreting counts or selecting live work.

Remote controllers retain their policy-digest, lease and owner-receipt contract in [remote-context.md](skills/herdr-foreman/references/remote-context.md). This extraction does not add receipt rotation: a policy upgrade requires an explicit verified reattachment, and existing remote deployment remains disabled until that authority is established. Do not erase owner stores to bypass a mismatch.

Inspect the executing policy identity from this checkout with:

```sh
python3 skills/herdr-foreman/policy-paths.py identity
```

The JSON reports the actual version, byte digest and policy root with
`authorizes_dispatch: false`. Native ACR identity verifies per-adapter Codex,
Claude Code and Cursor targets through public `acr list`/`acr check` metadata;
coordinator entries may coexist in a schema-2 ledger. Shared-skill execution
from `.agents/skills` is outside this reader. Fresh-process verification can
fetch locked dependencies and requires registry access.

## Development

See [docs/coordination-baseline.md](docs/coordination-baseline.md) and [docs/decisions/0001-background-progression.md](docs/decisions/0001-background-progression.md) for source measurements and the selected progression architecture.

Use Python 3.11+, Bash, Git, jq, Shellcheck 0.11.0 and Pyright 1.1.414. Check out the compatible coding-policy source for shared-helper integration tests; it is a development dependency, never vendored into this plugin.

```sh
HERDR_CODING_POLICY_ROOT=/absolute/path/to/coding-policy python3 scripts/run-tests.py
python3 scripts/run-diagnostics.py
tessl plugin lint .
acr validate . --json
```

The runner executes each Python and Bash suite separately with private XDG state. Tests import the canonical `skills/` sources without adding those paths to runtime subprocess environments. Select individual suites by passing their repository-relative paths. CI installs the published general-policy baseline outside the checkout and pins the ACR validator. It gates actual native installation and canonical Tessl skill review at 85%. Source package manifests share one explicit version.

PR events dispatch central policy review through `.github/workflows/review-trigger.yml`; the opt-in marker enables the scheduled backstop. The Codex subscription credential stays in coding-policy. Configure `FLEET_DISPATCH_TOKEN` as documented in `.env.example`.

CI uses a non-publishing `member` key for baseline access and an isolated skill-review job. The publisher key exists only in the `publish` [environment](https://github.com/jbaruch/herdr-policy/settings/environments), restricted to `main`; PR test code cannot obtain it. Creation, storage and renewal are documented in `.env.example`. [Tessl workspace roles](https://docs.tessl.io/administrators/roles) define these permissions.

Install the pinned local checks in your Python development environment with `python3 -m pip install -r requirements-dev.txt`, then run `pre-commit install`. Gitleaks blocks secret-shaped staged changes and redacts its findings. CI independently scans committed history with the same pinned scanner. Renew the scanner monthly in both `.pre-commit-config.yaml` and the test workflow; Dependabot renews the Python runner weekly.

See [CHANGELOG.md](CHANGELOG.md) for release history and [migration.md](docs/migration.md) for cutover and rollback.

The serialized publish workflow runs the gates once, publishes the explicit Tessl version, then creates the immutable ACR tag and asset in a dependent job. Each channel is confirmed separately; Tessl moderation must pass before consumer adoption. If only ACR fails, rerun failed jobs on that same run, preserving the successful Tessl job and original baseline. Never move an existing tag or rerun a successful Tessl publish to repair the other channel. This repository records dated changelog headings manually and does not add a stamp commit during publication.
