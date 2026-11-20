# Agentic Assistant {version}

An AI analyst built into FortiSOAR. It investigates alerts with cited verdicts,
stages containment for an analyst to approve, and turns an investigation into a
playbook that runs without it.

## What's in this bundle

| File | What it is |
|------|------------|
| `agentic-assistant-pack-{version}.zip` | The pack: everything below in one Import Wizard import |
| `docs/USER_GUIDE.md` | For analysts: investigating an alert, saving an investigation as a playbook, building and fixing playbooks, the Monitor queue |
| `docs/AGENTIC_ASSISTANT_GUIDE.md` | For administrators: configuration, guardrails and approvals, autonomy policy, native MCP tools, troubleshooting |
| `docs/PERSONA_AUTHORING.md` | Giving the assistant a module-specific role (its prompt, tools and write scope) |
| `docs/SKILLS_AUTHORING.md` | Teaching it your team's house rules |
| `RELEASE_NOTES.md` | What changed, release by release |

The pack (`{name}`) contains:

| Component | Version |
|-----------|---------|
| Connector: FSR Agentic Assistant (`connector-fsr-agentic-assistant`) | {connector} |
| Widget: Agentic Assistant (`agenticAssistant`) | {agenticAssistant} |
| Widget: Agentic Assistant Monitor (`agenticAssistantMonitor`) | {agenticAssistantMonitor} |
| Dashboard: Agentic Assistant Monitor | |
| Framework: `fsr-playbooks` (installed by the connector) | {framework} |

## Requirements

- FortiSOAR 8.0.
- An LLM the appliance can reach: an OpenAI or Anthropic API key, or an
  OpenAI-compatible endpoint.
- Shell access to the appliance for step 1, as `labuser` (its sudo rules allow
  `chattr` and `sed`, which is all step 1 needs; they do not allow `tee` or a
  root shell) or as root.
- The appliance can reach `pypi.org` over HTTPS.

## Install

Install with the **Import Wizard**, not Content Hub. A Content Hub upload
registers the pack and creates the dashboard but never installs the connector
or the widgets: FortiSOAR only installs a pack's bundled connector and widget
files through the Import Wizard (Content Hub installs them from Fortinet's
catalog, where these are not published).

1. **Let the connector installer use PyPI.** FortiSOAR installs connector
   Python libraries from its own package index, which does not carry
   `fsr-playbooks=={framework}`. Its pip configuration is locked read-only, so
   unlock it, add PyPI, and lock it again:

   ```
   F=/opt/cyops/configs/integrations/packages/integrations_env/pip.conf
   sudo chattr -i $F
   sudo sed -i -e '$a extra-index-url = https://pypi.org/simple/' -e '$a trusted-host = pypi.org' $F
   sudo chattr +i $F
   sudo cat $F
   ```

   The last command should show the two new lines under the existing
   `index-url`. Do this before step 3. Do not install the libraries by hand.
2. **Allow custom connectors and widgets.** Under System Settings, open
   Advanced Development Features, turn on custom connectors and custom
   widgets, and save. Without both, the Import Wizard holds back connectors
   and widgets that are not in Fortinet's catalog.
3. **Import the pack.** Open the Import Wizard, upload
   `agentic-assistant-pack-{version}.zip`, review the selections (the FSR SOC
   Assistant connector, both widgets and the Agentic Assistant Monitor dashboard
   should all be included), and import.
4. **Wait for the connector's libraries.** Open Automation > Connectors > FSR
   Agentic Assistant. Its requirements finish installing a few minutes after the
   import. Confirm the framework landed:

   ```
   sudo find /opt/cyops/configs/integrations/packages/integrations_env/conn_pkgs -maxdepth 5 -name 'fsr_playbooks-*.dist-info'
   ```

   If you imported before step 1, the install already failed, but the
   connector keeps showing its requirements as in progress and never offers a
   retry. FortiSOAR does not try again by itself. After step 1, re-run the
   install with the same call the connector page's retry link makes (as an
   administrator, using an API key or a session token):

   ```
   POST /api/integration/connectors/dependencies_check/connector-fsr-agentic-assistant/{connector}/?format=json
   ```

   It answers `Dependencies installation completed` in under a minute.
   The connector record may go on saying "in progress" afterwards; the
   `find` above and the health check in step 6 are the real test. The failure
   itself is in `/var/log/cyops/cyops-integrations/connectors.log`
   (`No matching distribution found for fsr-playbooks`).
5. **Publish the widgets.** The Import Wizard brings widgets in as drafts.
   Publish both Agentic Assistant and Agentic Assistant Monitor from the
   widget library.
6. **Configure the connector.** Add a configuration with at least an LLM
   provider and its key, and mark it as the default. Every field is described
   in `docs/AGENTIC_ASSISTANT_GUIDE.md` section 3.3. Its health check reports a
   missing or wrong `fsr-playbooks` install by name.
   Enter the key by hand. A configuration copied from another appliance through
   the API arrives with its key set to the text `NULL` (FortiSOAR never returns
   stored secrets), and the health check then fails with an OpenAI or Anthropic
   401 that names `NULL` as the key.
7. **Check it works.** Open any alert and click the assistant icon in the
   drawer, and ask it to investigate the alert. The Agentic Assistant Monitor
   dashboard should render.

### If something looks wrong

| Symptom | Cause and fix |
|---------|---------------|
| Content Hub shows the pack installed but no connector or widgets | It was uploaded through Content Hub. Import the same zip with the Import Wizard (step 3). |
| The Import Wizard does not offer the connector or widgets | Step 2 is not done; both switches must be on. |
| Connector requirements "in progress" for more than a few minutes | Step 1 missing or PyPI unreachable. See step 4 for the retry. |
| The assistant icon is missing from the alert drawer | The widgets were not published (step 5). |
| The assistant says the framework is missing or the wrong version | The connector's health check names the fault; fix step 1 and re-run the install (step 4). |
| Alerts list shows raw `{{ }}` panels on FortiSOAR 8.0.0 | Not this pack. The SOAR Framework 4.1.0 pack needs 8.0.1; on 8.0.0 its Alerts layout asks for Card Table 1.0.0 while shipping 1.0.1, which is 8.0.1-only. Install and publish Card Table 1.0.0, or upgrade FortiSOAR to 8.0.1. |

To upgrade, import the newer zip the same way. Connector configurations are
not included in the pack, so no credentials travel with it.

## Before you rely on it

- Anything that changes something (blocking an IP, isolating a host,
  updating a record, saving a playbook) waits for a person to approve it.
  `docs/AGENTIC_ASSISTANT_GUIDE.md` section 6 explains the tiers and who can
  approve.
- **Simulation Mode** in the connector configuration narrates actions without
  executing them. Use it for demos and training.
- Investigations use whatever connectors you have configured (firewall, EDR,
  SIEM, threat intelligence). An integration that is not configured is
  reported as missing.
