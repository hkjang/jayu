# CLI Coverage Map

Refresh this document with:

```bash
jayu inventory cli-coverage
```

## New Management Commands

| Command | Purpose |
| --- | --- |
| `jayu inventory build` | Generate feature inventory JSON and Markdown |
| `jayu inventory dashboard-coverage` | Generate dashboard coverage map |
| `jayu inventory cli-coverage` | Generate CLI coverage map |
| `jayu release doctor` | Run release-readiness checks |
| `jayu release notes` | Generate a release note from changed files |
| `jayu config wizard` | Create starter config and env template without storing secrets |

The generated JSON lives at `state/cli_coverage_map.json`.

