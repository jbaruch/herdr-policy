# jbaruch/herdr-policy

[![tessl](https://img.shields.io/endpoint?url=https%3A%2F%2Fapi.tessl.io%2Fv1%2Fbadges%2Fjbaruch%2Fherdr-policy)](https://tessl.io/registry/jbaruch/herdr-policy)

Herdr team coordination policy, distributed through Tessl and the Agentic Context Registry (ACR).

**Status: bootstrap.** The package defines its scope. Coordinator implementation, extraction from [coding-policy](https://github.com/jbaruch/coding-policy), and the first registry releases are tracked in [the implementation epic](https://github.com/jbaruch/herdr-policy/issues/1).

## Distribution

| Channel | Manifest | Identity |
| --- | --- | --- |
| Tessl | `.tessl-plugin/plugin.json` | `jbaruch/herdr-policy` |
| ACR | `agent-plugin.yaml` | `github:jbaruch/herdr-policy` |

Both manifests reference the same authored files and use the same version. This bootstrap has no coordinator scripts, worker skills, or lifecycle hooks.

## Package contents

| Rule | Purpose |
| --- | --- |
| [herdr-scope](rules/herdr-scope.md) | Define applicability and the bootstrap boundary |

No skills are included in this version.

## Installation

Registry installation will be available after the first releases. The intended commands are:

```sh
tessl install jbaruch/herdr-policy
```

```sh
acr install github:jbaruch/herdr-policy
acr realize
```

## Local validation

```sh
tessl plugin lint .
acr validate . --json
```

See [CHANGELOG.md](CHANGELOG.md) for package history.
