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
VVP_TIMEOUT_S = 1800

RESULT_RE = re.compile(r"RESULT (\w+)=(\S+)")


def sdf_path(corner):
    """Filtered (IOPATH-only) per-corner annotation.

    Icarus's interconnect annotator crashes on this design's SDF
    ("NULL handle passed to vpi_scan"), and without -ginterconnect the
    unfiltered file spews thousands of 'Could not find net' errors, so the
    corner SDF is reduced to per-cell IOPATH delays with
    tools/sdf/filter_sdf.py. Wire (interconnect) delays are therefore not
    annotated; the recorded first-failure boundary is accordingly a small
    optimistic offset (~1 ns at the slow corner) from the STA prediction.
    """
    return os.path.join(C.DATA, "sdf_path", f"{corner}.iopath.sdf")


def filter_sdf(corner):
    outdir = os.path.join(C.DATA, "sdf_path")
    os.makedirs(outdir, exist_ok=True)
    src = ("/work/artifacts/run-%s/sdf/%s/"
           % (C.RUN_ID, corner) + "tt_um_echoworld424_tpv__%s.sdf" % corner)
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


def run_point(period_ns, word, nframes, corner=None, forcecan=None):
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
        "+period=%d" % period_ns,
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
        SIMDIR, "run_p%d_w%04x%s.log"
        % (period_ns, word, "_" + corner if corner else "_zdelay"))
    open(log, "w").write(res.stdout + "\n===STDERR===\n" + res.stderr)
    # Surface annotation problems: unannotated IOPATH / bad instance refs.
    warns = [l for l in res.stderr.splitlines()
             if "IOPATH" in l or "SDF" in l.upper() or "annotat" in l.lower()]
    if warns:
        print("  vvp annotation warnings (%d lines, see log): %s%s" % (
            len(warns), warns[0][:120],
            " ..." if len(warns) > 1 else ""))
    fields = dict(RESULT_RE.findall(res.stdout))
    fields["log"] = os.path.basename(log)
    return fields


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--no-sdf", action="store_true",
                    help="zero-delay functional reference points only")
    args = ap.parse_args()
    os.makedirs(C.DATA, exist_ok=True)
    for corner in ("nom_slow_1p08V_125C", "nom_typ_1p20V_25C"):
        filter_sdf(corner)
    compile_tb()

    word = 0xFF << 0 | 1 << 8 | 3 << 10  # seg=3333, pat=WORST, cansel=3
    nframes = 8 if args.smoke else 200

    # Zero-delay functional reference: must be error-free at any period.
    points = [(20, None)]
    if not args.no_sdf:
        # Periods bracketing the STA-predicted slow-corner knee
        # (seg=3333, worst: 24.81 ns data path -> predicted T_fail 25.26 ns)
        # and the typ-corner knee (15.82 ns -> 16.19 ns).
        for t in (22, 24, 25, 26, 28, 30, 40):
            points.append((t, "nom_slow_1p08V_125C"))
        for t in (14, 16, 18, 20):
            points.append((t, "nom_typ_1p20V_25C"))

    rows = []
    for period, corner in points:
        f = run_point(period, word, nframes, corner, forcecan=1)
        row = {
            "corner": corner or "(zero-delay reference)",
            "period_ns": period,
            "freq_mhz": round(1e3 / period, 3),
            "cfg_word": "0x%04X" % (word | (1 << 14)),
            "segs": "3333",
            "pattern": "worst",
            "cansel": 3,
            "winsel": 0,
            "forcecan": 1,
            "nframes_req": nframes,
            "ops": f.get("ops", ""),
            "err_cnt": f.get("err_cnt", ""),
            "err_rate_per_op": (
                round(int(f["err_cnt"]) / int(f["ops"]), 6)
                if f.get("err_cnt") and f.get("ops") and int(f["ops"]) else ""),
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

    # RO canary cross-check: with the SDF annotated and the loops live
    # (FORCE_CAN off), the edge counters would measure the annotated
    # oscillation over a small window -- compare against the STA loop-delay
    # prediction in data/ro_predict.csv (P1.3). INVALID for that purpose:
    # pnr.sdc disables the RO timing arcs, so write_sdf emits hard 0.000
    # IOPATH triples for every u_ro_* cell (see
    # docs/ro-sdf-crosscheck-diagnosis.md). The loops then race at ~zero
    # delay and the counters latch deterministic simulator race artifacts,
    # not oscillation counts. The row is kept for its DUT error count only;
    # gen_cnt/mat_cnt are blanked here so they cannot be mistaken for RO
    # measurements. RO frequency prediction is the STA loop-delay model
    # (data/ro_predict.csv); extracted transient SPICE remains the
    # validation path if an engine becomes available.
    ro_frames = 30
    f = run_point(20, word, ro_frames, "nom_slow_1p08V_125C", forcecan=0)
    rows.append({
        "corner": "nom_slow_1p08V_125C",
        "period_ns": 20,
        "freq_mhz": 50.0,
        "cfg_word": "0x%04X" % (word & ~(1 << 14)),
        "segs": "3333",
        "pattern": "worst",
        "cansel": 3,
        "winsel": 0,
        "forcecan": 0,
        "nframes_req": ro_frames,
        "ops": f.get("ops", ""),
        "err_cnt": f.get("err_cnt", ""),
        "err_rate_per_op": (
            round(int(f["err_cnt"]) / int(f["ops"]), 6)
            if f.get("err_cnt") and f.get("ops") and int(f["ops"]) else ""),
        "gen_cnt": "",
        "mat_cnt": "",
        "cfg_echo": f.get("cfg_echo", ""),
        "stat": f.get("stat", ""),
        "err_dut": f.get("err_dut", ""),
        "ro_note": ("invalid: RO cells zero-annotated (disabled arcs); "
                    "counts blanked, see docs/ro-sdf-crosscheck-diagnosis.md"),
        "sdf": sdf_path("nom_slow_1p08V_125C"),
        "run_id": C.RUN_ID,
        "git_commit": C.GIT_COMMIT,
        "librelane_image": C.LL_IMAGE,
        "pdk_rev": C.CIEL_PDK_REV,
        "log": f.get("log", ""),
    })
    print("RO cross-check (DUT-only, RO counts blanked):",
          {k: f.get(k) for k in ("ops", "err_cnt", "cfg_echo")})

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
