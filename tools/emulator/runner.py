# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Build and launch helper for the emulator (runs inside the simulator env).

Wraps cocotb's runner API so the launcher only has to say *what* to run:

    run(backend="sdf", scenario="pvtsweep", corner="slow", ops=100)

Two builds exist:

  rtl  src/*.v + tb_emulator.v, compiled with -DTPV_GDELAY=1 (simulation-only
       gate delay so the ring-oscillator canaries actually oscillate).
  sdf  timing-safe stdcell library + renamed post-route netlist + tb_emulator.v,
       compiled with -gspecify and annotated at run time with a corner SDF.
"""

from __future__ import annotations

import os
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from . import artifacts
from .pvt import PVT, REPO, get_corner

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMULATOR = os.path.join(TOOLS, "emulator")
TB = os.path.join(EMULATOR, "tb_emulator.v")
BUILD_ROOT = os.path.join(REPO, "runs", "emulator", "build")
RESULTS_ROOT = os.path.join(REPO, "runs", "emulator", "results")

RTL_SOURCES = [
    "tt_um_echoworld424_tpv.v",
    "tpv_cells.v",
    "tpv_delay_line.v",
    "tpv_rca16.v",
    "tpv_checker.v",
    "tpv_pattern_gen.v",
    "tpv_ro_canary.v",
]


def _get_runner():
    try:
        from cocotb_tools.runner import get_runner   # cocotb >= 2.0
    except ImportError:                              # pragma: no cover
        from cocotb.runner import get_runner         # cocotb 1.x
    return get_runner(os.environ.get("SIM", "icarus"))


def simulator_fingerprint() -> str:
    """Short simulator identity, so host and devcontainer builds never mix.

    Icarus refuses to run a vvp file compiled by a different major version and
    cocotb's rebuild check only looks at source timestamps, so the build
    directory is keyed on the simulator version.
    """
    import re
    import subprocess
    try:
        out = subprocess.run(["iverilog", "-V"], capture_output=True,
                             text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    m = re.search(r"Icarus Verilog version (\S+)", out.stdout + out.stderr)
    return "iv" + re.sub(r"[^A-Za-z0-9._-]", "_", m.group(1) if m else "unknown")


def results_ok(path: str) -> bool:
    """True when results.xml exists and contains no failing test case."""
    if not os.path.isfile(path):
        return False
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return False
    cases = list(root.iter("testcase"))
    if not cases:
        return False
    for case in cases:
        if case.find("failure") is not None or case.find("error") is not None:
            return False
    return True


def build(backend: str, corner: Optional[PVT] = None, rebuild: bool = False,
          sdf: Optional[str] = None, netlist: Optional[str] = None,
          verbose: bool = False, runner=None) -> Dict[str, Any]:
    """Compile the requested backend; returns build metadata."""
    runner = runner or _get_runner()
    tag = backend if backend == "rtl" else "sdf"
    build_dir = os.path.join(BUILD_ROOT, "%s-%s" % (tag, simulator_fingerprint()))

    if backend == "rtl":
        sources = [os.path.join(REPO, "src", name) for name in RTL_SOURCES]
        sources.append(TB)
        defines: Dict[str, Any] = {"TPV_GDELAY": 1}
        build_args: List[str] = []
        meta: Dict[str, Any] = {"backend": "rtl", "sources": sources}
    elif backend == "sdf":
        art = artifacts.prepare(corner, sdf=sdf, netlist=netlist)
        sources = [art.stdcell_lib, art.netlist, TB]
        defines = {"TPV_SDF": 1}
        build_args = ["-gspecify"]
        meta = {
            "backend": "sdf",
            "sources": sources,
            "sdf": art.sdf,
            "netlist": art.netlist,
            "netlist_source": art.netlist_source,
            "sdf_source": art.sdf_source,
            "provenance": art.provenance,
        }
    else:
        raise ValueError("unknown backend %r (use rtl or sdf)" % backend)

    runner.build(
        sources=sources,
        hdl_toplevel="tb_emulator",
        build_dir=build_dir,
        always=bool(rebuild),
        defines=defines,
        build_args=build_args,
        timescale=("1ns", "1ps"),
        verbose=verbose,
    )
    meta["build_dir"] = build_dir
    meta["runner"] = runner
    return meta


def run(backend: str = "rtl", scenario: str = "hello",
        corner: Optional[PVT] = None, period_ns: float = 100.0,
        duty: float = 0.5, ops: Optional[int] = None,
        script: Optional[str] = None, waves: Optional[str] = None,
        sdf: Optional[str] = None, netlist: Optional[str] = None,
        extra_plusargs: Optional[Dict[str, Any]] = None,
        rebuild: bool = False, results_dir: Optional[str] = None,
        test_module: str = "emulator.session",
        verbose: bool = False) -> int:
    """Build and run one scenario.  Returns a process exit code."""
    runner = _get_runner()
    meta = build(backend, corner=corner, rebuild=rebuild, sdf=sdf,
                 netlist=netlist, verbose=verbose, runner=runner)

    plusargs: List[str] = [
        "+scenario=%s" % scenario,
        "+backend=%s" % backend,
        "+period=%.10g" % period_ns,
        "+duty=%.10g" % duty,
    ]
    if corner is not None:
        plusargs.append("+corner=%s" % corner.name)
    if ops is not None:
        plusargs.append("+ops=%d" % int(ops))
    if script:
        plusargs.append("+script=%s" % script)
    if waves:
        plusargs.append("+waves=%s" % waves)
    if backend == "sdf":
        plusargs.append("+sdf=%s" % meta["sdf"])
        plusargs.append("+netlist_source=%s" % meta["netlist_source"])
        plusargs.append("+sdf_source=%s" % meta["sdf_source"])
        prov = meta.get("provenance", {})
        if prov.get("netlist_sha256"):
            plusargs.append("+netlist_sha256=%s" % prov["netlist_sha256"])
        if prov.get("sdf_sha256"):
            plusargs.append("+sdf_sha256=%s" % prov["sdf_sha256"])
    for key, value in (extra_plusargs or {}).items():
        plusargs.append("+%s=%s" % (key, value))

    out_dir = results_dir or os.path.join(
        RESULTS_ROOT, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    xml = os.path.join(out_dir, "%s-%s.xml" % (
        scenario, corner.name if corner else backend))

    py_path = TOOLS
    if os.environ.get("PYTHONPATH"):
        py_path += os.pathsep + os.environ["PYTHONPATH"]

    runner = meta["runner"]
    runner.test(
        hdl_toplevel="tb_emulator",
        test_module=test_module,
        test_dir=TOOLS,
        build_dir=meta["build_dir"],
        plusargs=plusargs,
        extra_env={"PYTHONPATH": py_path},
        results_xml=xml,
    )

    ok = results_ok(xml)
    print("\nresults : %s" % xml)
    print("status  : %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1
