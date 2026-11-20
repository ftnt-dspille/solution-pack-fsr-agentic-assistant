#!/usr/bin/env python3
"""Build the Agentic Assistant solution pack from the component GitHub releases.

components.json pins one release tag per component. This script downloads each
release asset, reads every version from the info.json inside the tarball (so the
pack can only describe what it carries), repins the dashboard to the widget
versions it ships, writes the pack zip, checks it with pyfsr's export validator,
and writes the release bundle (pack + README + guides) next to it.

    python scripts/build.py                 # -> dist/
    python scripts/build.py --skip-validate # when pyfsr is not installed

Install the pack with the Import Wizard, not Content Hub: FortiSOAR installs
bundled connector and widget tarballs only on a non-solution-pack import, and
every Content Hub upload is typed 'SolutionPack Import'.

Set GH_TOKEN (or GITHUB_TOKEN) to avoid anonymous rate limits.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.request
import uuid as _uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
CACHE = ROOT / "cache"
DIST = ROOT / "dist"

DASHBOARD_TITLE = "Agentic Assistant Monitor"
PACK_LABEL = "Agentic Assistant"
# PERMANENT: Content Hub matches a later version to this name to upgrade in
# place, so renaming it orphans every installed copy.
PACK_NAME = "agenticAssistant"
PACK_PUBLISHER = "Fortinet CSE"
PACK_CATEGORY = ["Investigation", "Threat Hunting and Search", "Utilities"]
PACK_DESCRIPTION = (
    "An AI analyst built into FortiSOAR. It investigates alerts with cited "
    "verdicts, stages containment for an analyst to approve, and turns an "
    "investigation into a playbook that runs without it. Ships the FSR Agentic "
    "Assistant connector, the Agentic Assistant and Monitor widgets, and the "
    "Agentic Assistant Monitor dashboard.")
CONNECTOR_NAME = "connector-fsr-agentic-assistant"

# Bundle docs: (repo key, path in that repo at the pinned tag, path in bundle)
WIDGET_DOCS = [("docs/USER_GUIDE.md", "docs/USER_GUIDE.md"),
               ("docs/AGENTIC_ASSISTANT_GUIDE.md", "docs/AGENTIC_ASSISTANT_GUIDE.md")]
CONNECTOR_DOCS = [(f"{CONNECTOR_NAME}/docs/PERSONA_AUTHORING.md", "docs/PERSONA_AUTHORING.md"),
                  (f"{CONNECTOR_NAME}/docs/SKILLS_AUTHORING.md", "docs/SKILLS_AUTHORING.md"),
                  (f"{CONNECTOR_NAME}/release_notes.md", "RELEASE_NOTES.md")]


def _request(url: str) -> urllib.request.Request:
    req = urllib.request.Request(url, headers={"User-Agent": "agentic-assistant-pack-build"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and "github" in url:
        req.add_header("Authorization", f"Bearer {token}")
    return req


def fetch(url: str, dest: Path) -> Path:
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"fetch     : {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(_request(url)) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.rename(dest)
    return dest


def release_asset(repo: str, tag: str, pattern: str) -> Path:
    """The single release asset of repo@tag whose name matches pattern."""
    with urllib.request.urlopen(_request(
            f"https://api.github.com/repos/{repo}/releases/tags/{tag}")) as r:
        rel = json.load(r)
    hits = [a for a in rel.get("assets", []) if re.fullmatch(pattern, a["name"])]
    if len(hits) != 1:
        raise SystemExit(f"{repo}@{tag}: want exactly one asset matching {pattern!r}, "
                         f"found {[a['name'] for a in rel.get('assets', [])]}")
    a = hits[0]
    return fetch(a["browser_download_url"], CACHE / repo.replace("/", "__") / tag / a["name"])


def source(repo: str, tag: str) -> Path:
    """The repo's source tree at tag, extracted once into the cache."""
    d = CACHE / repo.replace("/", "__") / tag / "src"
    if not d.is_dir():
        tgz = fetch(f"https://codeload.github.com/{repo}/tar.gz/refs/tags/{tag}",
                    d.parent / "source.tar.gz")
        tmp = d.with_name("src.part")
        shutil.rmtree(tmp, ignore_errors=True)
        with tarfile.open(tgz) as t:
            t.extractall(tmp, filter="data")
        (top,) = tmp.iterdir()
        top.rename(d)
        tmp.rmdir()
    return d


def tgz_info(tgz: Path) -> dict:
    """info.json at the tarball's top-level directory."""
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            parts = m.name.strip("./").split("/")
            if len(parts) == 2 and parts[1] == "info.json":
                return json.load(t.extractfile(m))
    raise SystemExit(f"no <dir>/info.json in {tgz.name}")


def tgz_text(tgz: Path, suffix: str) -> str | None:
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            if m.name.endswith(suffix):
                return t.extractfile(m).read().decode()
    return None


def check_tag(kind: str, tag: str, version: str) -> None:
    if tag.lstrip("v") != version:
        raise SystemExit(f"{kind}: tag {tag} carries version {version}")


def validate(out: Path) -> None:
    from pyfsr.exports import Export, ExportKind
    arc = Export.open(out)
    findings = arc.problems()
    for f in findings:
        print(f"check     : {f}")
    errors = [f for f in findings if f.is_error]
    if errors or arc.kind is not ExportKind.SOLUTION_PACK:
        out.unlink()
        raise SystemExit(f"REFUSING: {out.name} is not a valid solution pack "
                         f"({len(errors)} error(s), kind={arc.kind.value})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--components", default=str(ROOT / "components.json"))
    ap.add_argument("--skip-validate", action="store_true")
    ap.add_argument("--no-bundle", action="store_true")
    ap.add_argument("--connector-tgz", default=None,
                    help="local connector tarball instead of the release asset (testing only)")
    ap.add_argument("--widget-tgz", action="append", default=[], metavar="NAME=PATH",
                    help="local widget tarball instead of the release asset (testing only)")
    ap.add_argument("--version", default=None, help="override pack_version (testing only)")
    args = ap.parse_args(argv)

    spec = json.loads(Path(args.components).read_text())
    version = args.version or spec["pack_version"]
    local_widgets = dict(x.split("=", 1) for x in args.widget_tgz)

    c = spec["connector"]
    conn_tgz = (Path(args.connector_tgz) if args.connector_tgz
                else release_asset(c["repo"], c["tag"], rf"{CONNECTOR_NAME}-.+\.tgz"))
    conn = tgz_info(conn_tgz)
    check_tag("connector", c["tag"], conn["version"])
    req = tgz_text(conn_tgz, f"{CONNECTOR_NAME}/requirements.txt") or ""
    m = re.search(r"^fsr-playbooks==(\S+)", req, re.M)
    framework = m.group(1) if m else "?"

    widgets = []
    for w in spec["widgets"]:
        local = local_widgets.get(w["name"])
        tgz = (Path(local) if local
               else release_asset(w["repo"], w["tag"], rf"{re.escape(w['name'])}-.+\.tgz"))
        info = tgz_info(tgz)
        if info["name"] != w["name"]:
            raise SystemExit(f"{w['repo']}@{w['tag']}: tarball is {info['name']}, want {w['name']}")
        if not local:
            check_tag(w["name"], w["tag"], info["version"])
        if info.get("development") is not False:
            raise SystemExit(f"REFUSING: widget {w['name']} {info['version']} has development="
                             f"{info.get('development')!r}; the pack ships release-form widgets only")
        widgets.append({**w, "version": info["version"], "tgz": tgz,
                        "title": info.get("title", w["name"])})

    dash = json.loads((ASSETS / f"{DASHBOARD_TITLE}.json").read_text())
    by_name = {w["name"]: w["version"] for w in widgets}
    for row in (dash.get("config") or {}).get("rows") or []:
        for col in row.get("columns") or []:
            for w in col.get("widgets") or []:
                pin = w.get("type") or ""
                name = pin.rsplit("-", 1)[0]
                if pin and name not in by_name:
                    raise SystemExit(f"REFUSING: dashboard renders {pin}, which the pack does not carry")
                if pin and pin != f"{name}-{by_name[name]}":
                    print(f"repin     : {pin} -> {name}-{by_name[name]}")
                    w["type"] = f"{name}-{by_name[name]}"

    DIST.mkdir(exist_ok=True)
    out = DIST / f"agentic-assistant-pack-{version}.zip"
    stage = DIST / ".packstage"
    shutil.rmtree(stage, ignore_errors=True)
    root = f"export_{_uuid.uuid4()}"
    base = stage / root
    for d in ("dashboards", "connectors", "widgets"):
        (base / d).mkdir(parents=True)

    (base / "dashboards" / f"{DASHBOARD_TITLE}.json").write_text(json.dumps(dash, indent=4))

    # The platform names connector tarballs <name>_<version>.tgz (underscore).
    conn_arc = f"{conn['name']}_{conn['version']}.tgz"
    shutil.copy2(conn_tgz, base / "connectors" / conn_arc)
    (base / "connectors" / "data.json").write_text(json.dumps([{
        "name": conn["name"], "label": conn["label"],
        "category": [conn["category"]] if isinstance(conn["category"], str) else conn["category"],
        "description": conn.get("description", ""),
        "publisher": conn.get("publisher", "Internal"),
        "version": conn["version"], "operation_roles": [], "configurations": [],
        "dataImports": [], "install_mode": "tgz", "installer_path": conn_arc,
    }], indent=4))

    wdata = []
    for w in widgets:
        arc = f"{w['name']}-{w['version']}.tgz"
        shutil.copy2(w["tgz"], base / "widgets" / arc)
        wdata.append({"name": w["name"], "version": w["version"], "title": w["title"],
                      "install_mode": "tgz", "installer_path": arc})
    (base / "widgets" / "data.json").write_text(json.dumps(wdata, indent=4))

    (base / "info.json").write_text(json.dumps({
        "name": PACK_NAME, "version": version, "type": "solutionpack", "local": True,
        "label": PACK_LABEL, "publisher": PACK_PUBLISHER, "description": PACK_DESCRIPTION,
        "prerequisite": (ASSETS / "prerequisite.md").read_text().replace("{framework}", framework),
        "help": None, "category": PACK_CATEGORY, "supportInfo": None, "iconLarge": None,
        "dependencies": [], "postInstallConfig": {"enabled": False},
        "fsrMinCompatibility": "8.0.0",
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "contents": {
            "dashboards": [{"name": DASHBOARD_TITLE}],
            "connectors": [{"name": conn["label"], "apiName": conn["name"],
                            "version": conn["version"]}],
            # `name` is the widget TITLE here; a `title` key is not read.
            "widgets": [{"apiName": w["name"], "name": w["title"]} for w in widgets],
        },
    }, indent=4))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(base.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(stage))
    shutil.rmtree(stage)
    if not args.skip_validate:
        validate(out)

    print(f"pack      : {PACK_NAME} {version}")
    print(f"connector : {conn['name']} {conn['version']}")
    for w in widgets:
        print(f"widget    : {w['name']} {w['version']}")
    print(f"framework : fsr-playbooks {framework}")
    print(f"wrote {out}  ({out.stat().st_size // 1024} KB)")

    fill = {"version": version, "name": PACK_NAME, "connector": conn["version"],
            "framework": framework, **by_name}
    (DIST / "versions.json").write_text(json.dumps(fill, indent=2))
    if args.no_bundle:
        return 0

    name = f"agentic-assistant-release-{version}"
    bstage = DIST / ".bundlestage" / name
    shutil.rmtree(bstage.parent, ignore_errors=True)
    bstage.mkdir(parents=True)
    shutil.copy2(out, bstage / out.name)
    readme = (ASSETS / "README.md").read_text()
    for k, v in fill.items():
        readme = readme.replace("{" + k + "}", str(v))
    (bstage / "README.md").write_text(readme)
    main_widget = next(w for w in widgets if w["name"] == "agenticAssistant")
    wsrc = source(main_widget["repo"], main_widget["tag"])
    csrc = source(c["repo"], c["tag"])
    (bstage / "docs").mkdir()
    for src, dst in WIDGET_DOCS:
        shutil.copy2(wsrc / src, bstage / dst)
    if (wsrc / "docs" / "images").is_dir():
        shutil.copytree(wsrc / "docs" / "images", bstage / "docs" / "images")
    for src, dst in CONNECTOR_DOCS:
        shutil.copy2(csrc / src, bstage / dst)
    bout = DIST / f"{name}.zip"
    with zipfile.ZipFile(bout, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(bstage.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(bstage.parent))
    shutil.rmtree(bstage.parent)
    print(f"wrote {bout}  ({bout.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
