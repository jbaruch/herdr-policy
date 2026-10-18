# Agent Rules

This repository is the `jbaruch/herdr-policy` plugin, distributed through Tessl and ACR.

- Keep `.tessl-plugin/plugin.json` and `agent-plugin.yaml` aligned on identity, version, and distributed content.
- Author shared content once in `rules/` and `skills/`; both manifests reference those files.
- Keep findings and implementation planning in the GitHub epic. The epic records evidence and proposals; it grants no runtime authority.
- Validate package changes with `tessl plugin lint .` and `acr validate . --json`.
- Preserve extracted owner/state contracts during relocation. Coordinator redesign and registry publication have separate acceptance evidence in the epic.

## Review Guidelines

Read every in-tree `rules/*.md` on the PR head. Apply general coding-policy rules to implementation and retain the Herdr-only scope of the team contract. Check both manifests against the same runtime files, and keep development suites outside declared skill trees. Cite policy findings with the rule name, file, line, violated clause and fix.
