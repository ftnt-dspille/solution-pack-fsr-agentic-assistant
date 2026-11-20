# Agentic Assistant solution pack

One FortiSOAR import that installs the Agentic Assistant: the connector, both
widgets and the Monitor dashboard.

**Download:** [agentic-assistant-pack.zip (latest)](https://github.com/ftnt-dspille/solution-pack-fsr-agentic-assistant/releases/latest/download/agentic-assistant-pack.zip)
· [all releases](https://github.com/ftnt-dspille/solution-pack-fsr-agentic-assistant/releases)

Install it with **Application Editor > Import Wizard**, not Content Hub. A
Content Hub upload registers the pack and its dashboard but skips the bundled
connector and widgets. Full steps are in the README inside
`agentic-assistant-release-<version>.zip`.

## What it carries

The pack is assembled from the component releases pinned in
[`components.json`](components.json):

| Component | Repository |
|---|---|
| Connector `connector-fsr-agentic-assistant` | [fsr-agentic-assistant-connector](https://github.com/ftnt-dspille/fsr-agentic-assistant-connector) |
| Widget `agenticAssistant` | [fsr-agentic-assistant-widget](https://github.com/ftnt-dspille/fsr-agentic-assistant-widget) |
| Widget `agenticAssistantMonitor` | [fsr-agentic-assistant-monitor-widget](https://github.com/ftnt-dspille/fsr-agentic-assistant-monitor-widget) |
| Dashboard: Agentic Assistant Monitor | [`assets/`](assets) (pinned widget version is rewritten at build time) |

## Cutting a pack release

1. Release the changed components first (each repo publishes on a `v<X.Y.Z>` tag).
2. Update their tags in `components.json` and bump `pack_version`.
3. `make build` to check locally, commit, then `git tag v<pack_version> && git push --tags`.

CI builds, validates (pyfsr export validator) and publishes the release.

```
make build      # dist/agentic-assistant-pack-<v>.zip + release bundle
make clean      # drop dist/ and the download cache
```
