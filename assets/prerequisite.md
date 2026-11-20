# Install with the Import Wizard, not Content Hub
FortiSOAR installs a pack's bundled connector and widget files only through the Import Wizard; a Content Hub install registers this pack and its dashboard but not the FSR Agentic Assistant connector or its widgets. Full steps are in the README that ships with the pack.

 1. Let the connector installer use PyPI: add `extra-index-url = https://pypi.org/simple/` and `trusted-host = pypi.org` to `/opt/cyops/configs/integrations/packages/integrations_env/pip.conf` (unlock with `sudo chattr -i`, append with `sudo sed -i -e '$a ...'`, lock again with `sudo chattr +i`; `labuser` may run those but not `tee`). It must be able to fetch `fsr-playbooks=={framework}`. If the pack was imported first, the connector's requirements stay "in progress" and are never retried: re-run them after this step (README step 4).
 2. System Settings > Advanced Development Features: allow custom connectors and custom widgets.
 3. Import Wizard: import this zip.
 4. Wait for the connector's requirements to finish installing, then publish both widgets (Agentic Assistant, Agentic Assistant Monitor).
 5. Add a connector configuration with an LLM provider and its key, and mark it as the default.
