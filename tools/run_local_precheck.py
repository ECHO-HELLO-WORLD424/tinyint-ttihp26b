#!/usr/bin/env python3
"""Run TT precheck with devcontainer Python and the pinned image's KLayout.

The devcontainer has the Python bindings; the LibreLane image has the native
KLayout executable. No dependencies are installed or replaced by this driver.
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

import common as C

root = Path(C.REPO)
views = Path(C.RUN_DIR)
gds = views / "gds/tt_um_echoworld424_tpv.gds"
shutil.copy2(C.netlist_path(), gds.with_suffix(".v"))
out = Path(C.DATA) / "verification"
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, PDK="ihp-sg13g2",
           PDK_ROOT=f"{C.PDK_HOST}/ciel/ihp-sg13g2/versions/{C.CIEL_PDK_REV}")
with tempfile.TemporaryDirectory(prefix="tpv-precheck-") as tmp:
    wrapper = Path(tmp) / "klayout"
    cmd = ["docker", "run", "--rm", "-v", f"{root}:{root}",
           "-v", f"{C.PDK_HOST}:{C.PDK_HOST}:ro", "-w", str(root / "tt/precheck"),
           C.LL_IMAGE, "klayout"]
    wrapper.write_text("#!/bin/sh\nexec " + shlex.join(cmd) + ' "$@"\n')
    wrapper.chmod(0o755)
    env["PATH"] = tmp + os.pathsep + env["PATH"]
    with (out / "precheck.log").open("w") as log:
        result = subprocess.run([sys.executable, "precheck.py", "--gds", str(gds)],
                                cwd=root / "tt/precheck", env=env,
                                stdout=log, stderr=subprocess.STDOUT)
    for path in (root / "tt/precheck/reports").glob("*"):
        if path.suffix in (".xml", ".md"):
            shutil.copy2(path, out / ("precheck-" + path.name))
    print((out / "precheck.log").read_text()[-2500:])
    raise SystemExit(result.returncode)
