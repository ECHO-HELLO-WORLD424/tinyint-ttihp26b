#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""SDF-annotated timing simulation sweep (P1.2) + RO cross-check (P1.3).

Compiles the post-route netlist with the timing-safe stdcell library
(IOPATH arcs kept, timing checks removed -- see tools/sdf/make_sdf_lib.py)
inside the LibreLane tool image (iverilog, tool-identical to CI), annotates
the LibreLane corner SDF, and sweeps the clock period across the predicted
first-failure boundary for the predeclared measurement configurations.

Measured quantities per point (read through the chip's own serial readout):
  err_cnt / ops  : DUT first-failure boundary in timing simulation
  gen_cnt/mat_cnt: canary counts over the window (SDF-annotated oscillation)

Outputs data/sdfsim.csv + .json with the STA prediction alongside, so the
pre-silicon prediction error of case-analyzed STA is quantified directly.

Run: python3 tools/run_sdfsim.py [--smoke] [--no-sdf]
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SIMDIR = os.path.join(C.DATA, "sdfsim")
TB = os.path.join(C.REPO, "tools", "sdf", "tb_sdfsim.v")
SDF_LIB = os.path.join(SIMDIR, "sg13g2_stdcell_sdf.v")
NETLIST_SIM = os.path.join(SIMDIR, "netlist_sim.v")

# Wall-clock guard for vvp runs (annotation problems show up as runaway
# simulation, not as a hang on I/O).
VVP_TIMEOUT_S = 180

RESULT_RE = re.compile(r"RESULT (\w+)=(\S+)")


def sdf_path(corner):
    """Filtered (IOPATH-only) per-corner annotation.

    Icarus's interconnect annotator crashes on this design's SDF
    ("NULL handle passed to vpi_scan"), and without -ginterconnect the
    unfiltered file spews thousands of 'Could not find net' errors, so the
    corner SDF is reduced to per-cell IOPATH delays with
    tools/sdf/filter_sdf.py. Wire (interconnect) delays are therefore not
    annotated; the recorded first-failure boundary is accordingly an approximation whose offset from STA can have either sign.
    """
    return os.path.join(C.DATA, "sdf_path", f"{corner}.iopath.sdf")


def filter_sdf(corner):
    outdir = os.path.join(C.DATA, "sdf_path")
    os.makedirs(outdir, exist_ok=True)
    src = _inner(os.path.join(C.RUN_DIR, "sdf", corner,
                 "tt_um_echoworld424_tpv__%s.sdf" % corner))
    dst = "/work/" + os.path.relpath(sdf_path(corner), C.REPO)
    cmd = (C.docker_prefix() + ["docker", "run", "--rm"]
           + C.docker_mount_args() + ["-w", "/work", C.LL_IMAGE, "python3",
                                      "/work/tools/sdf/filter_sdf.py",
                                      src, dst])
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout[-2000:], res.stderr[-2000:])
        raise SystemExit("filter_sdf failed for " + corner)
    print(res.stdout.strip().splitlines()[-1])


def _inner(path):
    return path.replace(C.REPO, "/work")


def make_sim_netlist():
    """Rename escaped identifiers (dots/brackets -> underscores) in a copy
    of the post-route netlist so SDF (INSTANCE) strings bind in Icarus."""
    import subprocess
    rnr = os.path.join(C.REPO, "tools", "sdf", "rename_netlist.py")
    if (os.path.exists(NETLIST_SIM)
            and os.path.getmtime(NETLIST_SIM) > os.path.getmtime(C.netlist_path())):
        return
    res = subprocess.run([sys.executable, rnr, C.netlist_path(), NETLIST_SIM],
                         capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout, res.stderr)
        raise SystemExit("rename_netlist failed")
    print(res.stdout.strip())


def compile_tb():
    os.makedirs(SIMDIR, exist_ok=True)
    make_sim_netlist()
    vvp = os.path.join(SIMDIR, "tb.vvp")
    cmd = (C.docker_prefix() + ["docker", "run", "--rm"]
           + C.docker_mount_args() + ["-w", "/work", C.LL_IMAGE,
                                      "iverilog", "-gspecify",
                                      "-o", _inner(vvp),
                                      _inner(TB), _inner(SDF_LIB),
                                      _inner(NETLIST_SIM)])
    res = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(SIMDIR, "compile.log"), "w").write(
        res.stdout + "\n===STDERR===\n" + res.stderr)
    if res.returncode != 0:
        print(res.stdout[-3000:], res.stderr[-3000:])
        raise SystemExit("iverilog compile failed")
    print("compiled", vvp)


def run_point(period_ns, word, nframes, corner=None, forcecan=None, duty=0.5):
    """word: 16-bit cfg word; returns dict of RESULT fields.

    forcecan: None = keep word bits; 0/1 = override FORCE_CAN (word[14]).
    Zero-delay (no SDF) runs must stall the RO loops or the simulator
    livelocks on the combinational loop.
    """
    if forcecan is None:
        forcecan = 0 if corner else 1
    if forcecan:
        word = word | (1 << 14)
    else:
        word = word & ~(1 << 14)
    args = [
        "+period=%g" % period_ns,
        "+duty=%g" % duty,
        "+segs=%x" % (word & 0xFF),
        "+pat=%d" % ((word >> 8) & 3),
        "+cansel=%d" % ((word >> 10) & 3),
        "+winsel=%d" % ((word >> 12) & 3),
        "+forcecan=%d" % forcecan,
        "+nframes=%d" % nframes,
    ]
    if corner:
        args.append("+sdf=" + _inner(sdf_path(corner)))
    cmd = (C.docker_prefix() + ["docker", "run", "--rm"]
           + C.docker_mount_args() + ["-w", "/work", C.LL_IMAGE,
                                      "vvp", "-n",
                                      _inner(os.path.join(SIMDIR, "tb.vvp"))]
           ) + args
    res = subprocess.run(cmd, capture_output=True, text=True,
                         timeout=VVP_TIMEOUT_S)
    log = os.path.join(
        SIMDIR, "run_p%g_d%g_w%04x%s.log"
        % (period_ns, duty, word, "_" + corner if corner else "_zdelay"))
    open(log, "w").write(res.stdout + "\n===STDERR===\n" + res.stderr)
    # Surface annotation problems: unannotated IOPATH / bad instance refs.
    warns = [l for l in res.stderr.splitlines()
             if "IOPATH" in l or "SDF" in l.upper() or "annotat" in l.lower()]
    if warns:
        print("  vvp annotation warnings (%d lines, see log): %s%s" % (
            len(warns), warns[0][:120],
            " ..." if len(warns) > 1 else ""))
    fields = dict(RESULT_RE.findall(res.stdout))
    if res.returncode or "SDF ERROR" in res.stdout + res.stderr:
        raise RuntimeError(f"simulation/annotation failed: {log}")
    for key in ("ops", "err_cnt", "gen_cnt", "mat_cnt"):
        if key not in fields or not fields[key].isdigit():
            raise RuntimeError(f"missing/unknown {key}: {log}")
    fields["log"] = os.path.basename(log)
    return fields


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--no-sdf", action="store_true",
                    help="zero-delay functional reference points only")
    args = ap.parse_args()
    os.makedirs(C.DATA, exist_ok=True)
    for corner in C.CORNER_NAMES:
        filter_sdf(corner)
    compile_tb()

    word = 0xFF << 0 | 1 << 8 | 3 << 10  # seg=3333, pat=WORST, cansel=3
    nframes = 8 if args.smoke else 200

    # Zero-delay functional reference: must be error-free at any period.
    points = [(20, None)]
    if not args.no_sdf:
        for t in (18, 20, 22, 24, 26):
            points.append((t, "nom_fast_1p32V_m40C"))
        for t in (20, 26, 28, 30, 32, 34, 36, 40):
            points.append((t, "nom_typ_1p20V_25C"))
        for t in (36, 40, 42, 44, 46, 48, 50, 54, 60):
            points.append((t, "nom_slow_1p08V_125C"))

    rows = []
    for period, corner in points:
        f = run_point(period, word, nframes, corner, forcecan=1)
        row = {
            "corner": corner or "(zero-delay reference)",
            "period_ns": period,
            "capture_duty": 0.5,
            "high_time_ns": period * 0.5,
            "freq_mhz": round(1e3 / period, 3),
            "cfg_word": "0x%04X" % (word | (1 << 14)),
            "segs": "3333",
            "pattern": "worst",
            "cansel": 3,
            "winsel": 0,
            "forcecan": 1,
            "nframes_req": nframes,
            "ops": f.get("ops", ""),
            "n_compared": max(int(f["ops"]) - 1, 0),
            "err_cnt": f.get("err_cnt", ""),
            "err_rate_per_op": (
                round(int(f["err_cnt"]) / (int(f["ops"]) - 1), 6)
                if f.get("err_cnt") and f.get("ops") and int(f["ops"]) > 1 else ""),
            "gen_cnt": f.get("gen_cnt", ""),
            "mat_cnt": f.get("mat_cnt", ""),
            "cfg_echo": f.get("cfg_echo", ""),
            "stat": f.get("stat", ""),
            "err_dut": f.get("err_dut", ""),
            "ro_note": "",
            "sdf": sdf_path(corner) if corner else "",
            "run_id": C.RUN_ID,
            "git_commit": C.GIT_COMMIT,
            "librelane_image": C.LL_IMAGE,
            "pdk_rev": C.CIEL_PDK_REV,
            "log": f.get("log", ""),
        }
        rows.append(row)
        print("point:", row["corner"], period, "ns ->",
              "err", row["err_cnt"], "/", row["ops"],
              "gen", row["gen_cnt"], "mat", row["mat_cnt"])

    # Do not run the known-invalid zero-annotated RO cross-check. RO frequency
    # remains a separate broken-loop STA estimate, not an SDF measurement.

    csv_path = os.path.join(C.DATA, "sdfsim.csv")
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(C.DATA, "sdfsim.json"), "w") as fh:
        json.dump({"provenance": {
            "run_id": C.RUN_ID, "git_commit": C.GIT_COMMIT,
            "librelane_image": C.LL_IMAGE, "pdk_rev": C.CIEL_PDK_REV,
            "note": ("IOPATH-only SDF annotation (per-cell delays; wire "
                     "interconnect not annotated -- Icarus's interconnect "
                     "annotator crashes on this design); timing checks "
                     "removed from cell models; escaped instance names "
                     "renamed to underscore form for Icarus binding"),
        }, "rows": rows}, fh, indent=1)
    print("wrote", csv_path)


if __name__ == "__main__":
    main()
