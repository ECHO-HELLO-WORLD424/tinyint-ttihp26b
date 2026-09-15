#!/usr/bin/env python3
"""Record the local development build honestly, including setup signoff status."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import common as C

root = Path(C.REPO)
views = Path(C.RUN_DIR)
# RUN_DIR is either a local run's `final/` view (identity files and
# 54-openroad-stapostpnr/ live in its parent) or an archived run root as staged
# under artifacts/ (identity files sit next to the views).
run = views.parent if (views.parent / "resolved.json").exists() else views
out = Path(C.DATA) / "verification"
out.mkdir(parents=True, exist_ok=True)

def git(*args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

def record(path):
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size}

sources = {}
for path in sorted((root / "src").glob("*.v")) + [root / "src/config.json", root / "src/pnr.sdc", root / "src/user_config.json"]:
    rel = str(path.relative_to(root))
    original = subprocess.check_output(["git", "show", f"{C.GIT_COMMIT}:{rel}"], cwd=root)
    assert original == path.read_bytes(), f"Physical input changed since build: {rel}"
    sources[rel] = record(path)

metrics = json.loads((views / "metrics.json").read_text())
tests = {}
for name in ("rtl-results.xml", "gl-results.xml", "precheck-results.xml"):
    cases = ET.parse(out / name).findall(".//testcase")
    failures = sum(c.find("failure") is not None or c.find("error") is not None for c in cases)
    skipped = sum(c.find("skipped") is not None for c in cases)
    assert cases and failures == 0, name
    tests[name] = {"passed": len(cases) - skipped, "skipped": skipped, "failures": failures}
for name in ("structure.json", "aperture-check.json"):
    assert json.loads((out / name).read_text())["passed"]

files = {str(p.relative_to(root)): record(p) for p in sorted(views.rglob("*")) if p.is_file()}
for p in (run / "resolved.json", run / "54-openroad-stapostpnr/summary.rpt"):
    files[str(p.relative_to(root))] = record(p)
packages = {name: importlib.metadata.version(name) for name in ("cocotb", "gdstk", "klayout", "PyYAML")}
image = json.loads(subprocess.check_output(["docker", "image", "inspect", C.LL_IMAGE], text=True))[0]
setup_clean = all(v >= 0 for k, v in metrics.items() if k.startswith("timing__setup__ws"))
kind = ("local development experiment; not a submitted/green CI build"
        if C.RUN_ID.startswith("local-") else
        "archived CI build (run %s) with local verification" % C.RUN_ID)
manifest = {
    "kind": kind,
    "run_id": C.RUN_ID, "build_commit": C.GIT_COMMIT,
    # The working tree's HEAD. Overridable because a container bind mount can
    # serve a stale copy of .git/refs, which would record the wrong commit.
    "analysis_head": os.environ.get("TPV_ANALYSIS_HEAD", git("rev-parse", "HEAD")),
    "branch": git("branch", "--show-current"),
    "analysis_worktree_dirty": bool(git("status", "--porcelain")),
    "source_files_verified_equal_to_build_commit": sources,
    "tool_image": C.LL_IMAGE, "image_id": image["Id"],
    "image_repo_digests": image.get("RepoDigests", []), "pdk_revision": C.CIEL_PDK_REV,
    "support_tools_commit": git("-C", "tt", "rev-parse", "HEAD"),
    "devcontainer_python_packages": packages, "tests": tests,
    "active_area_um2": metrics["design__instance__area__stdcell"],
    "utilization_pct": 100 * metrics["design__instance__utilization"],
    "physical_metrics": metrics,
    "hardening_exit_status": 0 if setup_clean else 1,
    "hardening_failure": None if setup_clean else "Unchanged 20 ns/50% duty setup signoff fails in typical corner; intentional DUT aperture violations. Not waived.",
    "remaining": ([] if setup_clean else ["submission setup policy unresolved"]) + [
                  "RO frequencies are broken-loop STA models, not transient-validated",
                  "actual board duty/voltage/thermal limits unverified"],
    "analysis_source_files": {str(p.relative_to(root)): record(p)
                              for p in sorted((root / "tools").rglob("*"))
                              if p.is_file() and p.suffix in (".py", ".tcl", ".v")},
    "verification_source_files": {"test/test.py": record(root / "test/test.py"),
                                  "test/Makefile": record(root / "test/Makefile")},
    "local_view_files": files,
}
(out / "local-build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
for source in (views / "metrics.json", run / "54-openroad-stapostpnr/summary.rpt"):
    (out / source.name).write_bytes(source.read_bytes())
print("Local manifest: source identity, functional tests, precheck, structure and aperture checks verified")
