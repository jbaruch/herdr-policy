# Agent Rules

This repository is the `jbaruch/herdr-policy` plugin, distributed through Tessl and ACR.

- Keep `.tessl-plugin/plugin.json` and `agent-plugin.yaml` aligned on identity, version, and distributed content.
- Author shared content once in `rules/` and `skills/`; both manifests reference those files.
- Keep findings and implementation planning in the GitHub epic. The epic records evidence and proposals; it grants no runtime authority.
- Validate package changes with `tessl plugin lint .` and `acr validate . --json`.
- Bootstrap contents define package scope only. Migration, coordinator implementation, and registry publication are separate work tracked by the epic.
