#!/usr/bin/env python3
"""Install the pack on a FortiSOAR box and prove what landed.

    python scripts/install_proof.py <pack.zip> --instance <pyfsr alias> [--method hub|wizard|both]

The box is reached through the pyfsr instance registry (~/.pyfsr/instances.toml).

--method hub     Content Hub upload (POST /api/3/solutionpacks/install), the path
                 an analyst gets from Content Hub > Upload.
--method wizard  Import Wizard (configuration import), which installs bundled
                 connector and widget tarballs.
--method both    (default) hub first; if hub leaves the connector or a widget
                 uninstalled, run the wizard on top and check again.

Each check reads the box back: the pack record, the dashboard, the connector
(installed version and install status), and every widget (installed version,
draft state, and its registered controllers, which must be the production
<name><ver>Ctrl form, never DevCtrl).

The box must not already hold the pack's connector or widgets (that would
prove nothing); --allow-present overrides that. Exit 0 only when every check
passes after the last method run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import warnings
import zipfile
from pathlib import Path

warnings.filterwarnings("ignore")


def pack_manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        info = next(n for n in z.namelist() if n.count("/") == 1 and n.endswith("/info.json"))
        root = info.split("/")[0]
        man = json.loads(z.read(info))
        man["_connectors"] = json.loads(z.read(f"{root}/connectors/data.json"))
        man["_widgets"] = json.loads(z.read(f"{root}/widgets/data.json"))
    return man


def served(c, name: str, version: str) -> dict:
    """What the box actually serves for an installed widget: the controllers
    its .js files register, and the development flag of its info.json."""
    base = f"{c.base_url.rstrip('/')}/widgets/installed/{name}-{version}"
    ctrls: list[str] = []
    dev = None
    for f in ("view.controller.js", "edit.controller.js"):
        try:
            r = c.session.get(f"{base}/{f}", verify=False, timeout=30)
            if r.status_code == 200:
                ctrls += re.findall(r"\.controller\(\s*['\"]([A-Za-z0-9]+Ctrl)['\"]", r.text)
        except Exception:  # noqa: BLE001
            pass
    try:
        r = c.session.get(f"{base}/info.json", verify=False, timeout=30)
        if r.status_code == 200:
            dev = r.json().get("development")
    except Exception:  # noqa: BLE001
        pass
    return {"controllers": sorted(set(ctrls)), "served_development": dev}


def state(c, man: dict) -> dict:
    out: dict = {"connector": {}, "widgets": {}, "dashboards": [], "pack": None}
    # The list endpoint ignores a search term; read the whole inventory.
    inventory = c.get("/api/integration/connectors/", params={"page_size": 1000}).get("data") or []
    for conn in man["_connectors"]:
        hit = [r for r in inventory if r.get("name") == conn["name"]]
        out["connector"][conn["name"]] = [
            {"version": r.get("version"), "status": r.get("status"),
             "requirements_installed": r.get("requirements_installed")} for r in hit]
    for w in man["_widgets"]:
        recs = [m for m in c.get("/api/3/widgets", params={"$limit": 500}).get("hydra:member", [])
                if m.get("name") == w["name"]]
        out["widgets"][w["name"]] = [
            {"version": m.get("version"), "installed": m.get("installed"), "draft": m.get("draft"),
             **served(c, w["name"], m.get("version"))}
            for m in recs]
    dash = c.get("/api/3/dashboard", params={"$limit": 200})
    rows = dash.get("hydra:member", dash) if isinstance(dash, dict) else dash
    title = man["contents"]["dashboards"][0]["name"]
    out["dashboards"] = [
        {"uuid": d.get("uuid"),
         "widgets": [w.get("type") for r in (d.get("config") or {}).get("rows") or []
                     for col in r.get("columns") or [] for w in col.get("widgets") or []]}
        for d in rows if d.get("displayName") == title]
    sp = c.get("/api/3/solutionpacks", params={"name": man["name"], "$limit": 20}).get("hydra:member", [])
    sp = [p for p in sp if p.get("name") == man["name"]]
    out["pack"] = [{"version": p.get("version"), "installed": p.get("installed"),
                    "draft": p.get("draft")} for p in sp]
    return out


def checks(st: dict, man: dict) -> list[tuple[str, bool, str]]:
    res = []
    want_v = man["version"]
    res.append(("pack registered", any(p["version"] == want_v and p["installed"] for p in st["pack"] or []),
                json.dumps(st["pack"])))
    for conn in man["_connectors"]:
        got = st["connector"].get(conn["name"]) or []
        ok = any(r["version"] == conn["version"] for r in got)
        res.append((f"connector {conn['name']} {conn['version']} installed", ok, json.dumps(got)))
    for w in man["_widgets"]:
        got = [r for r in st["widgets"].get(w["name"]) or [] if r["version"] == w["version"]]
        res.append((f"widget {w['name']} {w['version']} installed",
                    any(r["installed"] for r in got), json.dumps(got)))
        ctrls = [x for r in got for x in r["controllers"]]
        res.append((f"widget {w['name']} serves production controllers (no DevCtrl)",
                    bool(ctrls) and not any("DevCtrl" in x for x in ctrls), json.dumps(ctrls)))
        devs = [r["served_development"] for r in got]
        # The box does not always serve info.json (null = not served); the
        # build already refuses a widget tarball whose info.json is not false.
        res.append((f"widget {w['name']} is not served as development true",
                    bool(devs) and not any(d is True for d in devs), json.dumps(devs)))
    pins = {f"{w['name']}-{w['version']}" for w in man["_widgets"]}
    dash_ok = any(d["widgets"] and set(d["widgets"]) <= pins for d in st["dashboards"])
    res.append(("dashboard present and pinned to the shipped widgets", dash_ok, json.dumps(st["dashboards"])))
    return res


def report(label: str, res) -> bool:
    print(f"\n== {label}")
    for name, ok, detail in res:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"        {detail[:400]}")
    return all(ok for _, ok, _ in res)


def wait_connector(c, man: dict, timeout: float = 900) -> None:
    """The connector's requirements install after the import; wait for them."""
    end = time.time() + timeout
    names = [x["name"] for x in man["_connectors"]]
    while time.time() < end:
        try:
            st = state(c, man)["connector"]
        except Exception as e:  # noqa: BLE001 - services recycle during a connector install
            print(f"   box not answering ({type(e).__name__}); retrying")
            time.sleep(20)
            continue
        rows = [r for n in names for r in st.get(n) or []]
        if rows and all(str(r.get("status") or "").lower() not in ("in-progress", "in progress", "")
                        for r in rows):
            return
        time.sleep(15)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack")
    ap.add_argument("--instance", required=True)
    ap.add_argument("--method", choices=["hub", "wizard", "both"], default="both")
    ap.add_argument("--allow-present", action="store_true")
    ap.add_argument("--check-only", action="store_true", help="install nothing; check what the box holds")
    ap.add_argument("--json", default=None, help="write every state snapshot here")
    args = ap.parse_args(argv)

    from pyfsr.instances import InstanceRegistry
    c = InstanceRegistry.load().client(args.instance)
    path = Path(args.pack)
    man = pack_manifest(path)
    log: dict = {"pack": man["name"], "version": man["version"], "instance": args.instance}

    before = state(c, man)
    log["before"] = before
    if args.check_only:
        ok = report("box state", checks(before, man))
        print("\nRESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    present = [n for n, v in before["connector"].items() if v] + [n for n, v in before["widgets"].items() if v]
    if present and not args.allow_present:
        print(f"REFUSING: the box already holds {present}; installing over them proves nothing "
              "(--allow-present to override)")
        return 2

    dev = c.system_settings.get_development_mode()
    if not (dev.get("connectors") and dev.get("widgets")):
        print(f"development features before: {dev}; enabling custom connectors and widgets")
        c.system_settings.set_development_mode(connectors=True, widgets=True)

    ok = False
    if args.method in ("hub", "both"):
        print(f"\n>> Content Hub upload: {path.name}")
        job = c.solution_packs.install_from_file(str(path), replace=True, force=True, wait=True, timeout=900)
        print(f"   job: {getattr(job, 'status', job)}")
        wait_connector(c, man, timeout=300)
        log["after_hub"] = st = state(c, man)
        ok = report("after Content Hub install", checks(st, man))
    if args.method == "wizard" or (args.method == "both" and not ok):
        print(f"\n>> Import Wizard: {path.name}")
        res = c.import_config.import_file(str(path))
        print(f"   job: {getattr(res, 'status', res)}")
        wait_connector(c, man)
        for w in man["_widgets"]:
            for m in c.widgets.list(name=w["name"]):
                if m.version == w["version"] and m.draft:
                    print(f"   publishing draft widget {w['name']} {w['version']}")
                    c.widgets.publish(m.uuid)
        log["after_wizard"] = st = state(c, man)
        ok = report("after Import Wizard install", checks(st, man))

    if args.json:
        Path(args.json).write_text(json.dumps(log, indent=2, default=str))
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
