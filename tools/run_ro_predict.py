#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""RO canary loop-delay prediction driver (P1.3).

For every PVT corner and canary tap selection (can_sel 0..3), measures the
extracted loop delay of both canary ring oscillators (broken-loop STA with
SPEF parasitics) and derives:

  f_osc [MHz]      = 1 / (2 * T_loop)
  count[win]       = floor(window_cycles * T_clk / (2 * T_loop))
  overflow flag    = count > 65535 (16-bit edge counters)

T_loop is the FULL loop period, the sum of two measured segments around the
ring (see tools/ro/ro_predict.tcl):

  line segment: nand_out (u_a3/X) -> line -> tail -> u_close -> close -> u_a2/A
  gate segment: u_a2/A -> u_a2/X (g2) -> u_a3/B -> nand_out (u_a3/X)

Each segment is measured with the loop broken OUTSIDE the segment (line: at
u_a2 A->X; gate: at u_close A->Y), so every physical arc of the loop is
counted exactly once. The gate segment (u_a2/u_a3, part of the loop closure)
was missing from the first-pass model.

Outputs data/ro_predict.csv + .json, plus per-corner raw provenance:
data/ro_cases_<corner>.tcl (case script; segment pins selected at sta runtime
from ES_RO_MODE) and data/ro_report_<corner>.txt (both raw segment reports,
marked with their ES_RO_MODE).

Run: python3 tools/run_ro_predict.py [--smoke]
"""

import argparse
import csv
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def gen_cases_tcl(path, sels):
    """Per-can_sel report cases for both ROs.

    One file serves both segment measurements: the -from/-to pins are
    selected at sta runtime from ES_RO_MODE (see tools/ro/ro_predict.tcl).
    """
    lines = [
        'if {$::env(ES_RO_MODE) eq "line"} {',
        '  set ro_frm_fmt {u_ro_%s.u_gate.u_a3/X}',
        '  set ro_to_fmt {u_ro_%s.u_gate.u_a2/A}',
        '} else {',
        '  set ro_frm_fmt {u_ro_%s.u_gate.u_a2/A}',
        '  set ro_to_fmt {u_ro_%s.u_gate.u_a3/X}',
        '}',
    ]
    for sel in sels:
        lines.append(f'puts "==ROCASE sel={sel}"')
        lines.append(f'ro_case_net {sel & 1} {{can_sel[0]}}')
        lines.append(f'ro_case_net {(sel >> 1) & 1} {{can_sel[1]}}')
        for ro in ("gen", "mat"):
            lines.append(f'puts "RO-{ro.upper()}"')
            lines.append(
                "set_max_delay 1000 "
                "-from [get_pins [format $ro_frm_fmt %s]] "
                "-to [get_pins [format $ro_to_fmt %s]]" % (ro, ro))
            lines.append(
                "report_checks "
                "-from [get_pins [format $ro_frm_fmt %s]] "
                "-to [get_pins [format $ro_to_fmt %s]] "
                "-path_delay max -group_path_count 1 "
                "-fields {slew cap} "
                "-format full_clock_expanded -corner nom" % (ro, ro))
        lines.append('puts "RO-END"')
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def parse_ro_report(text):
    """{sel: {'gen': block, 'mat': block}} via RO markers."""
    cases, cur_key, cur, kind = {}, None, None, None
    for line in text.splitlines():
        if line.startswith("==ROCASE "):
            cur_key = line[len("==ROCASE "):].strip()
            cases[cur_key] = {}
            cur, kind = None, None
            continue
        if line.startswith("RO-GEN") or line.startswith("RO-MAT"):
            if cur is not None:
                cases[cur_key][kind] = "\n".join(cur)
            kind = "gen" if line.startswith("RO-GEN") else "mat"
            cur = []
            continue
        if line.startswith("RO-END") and cur is not None:
            cases[cur_key][kind] = "\n".join(cur)
            cur, kind = None, None
            continue
        if cur is not None:
            cur.append(line)
    return {k: {kk: C.parse_path_block(vv) for kk, vv in v.items()}
            for k, v in cases.items()}


def loop_delay_ns(block):
    if not block or block.get("arrival_ns") is None:
        return None
    # unconstrained comb path: arrival at the -to pin IS the segment delay
    return block["arrival_ns"]


def run_ro(corner, cases_tcl, mode):
    libs = " ".join(
        C.PDK_INNER + "/" + rel for rel in C.CORNER_LIBS[corner])
    env = {
        "ES_LIBS": libs,
        "ES_NETLIST": C.netlist_path().replace(C.REPO, "/work"),
        "ES_SPEF": C.spef_path().replace(C.REPO, "/work"),
        "ES_CASES_TCL": cases_tcl.replace(C.REPO, "/work"),
        "ES_RO_MODE": mode,
    }
    cmd = C.docker_prefix() + ["docker", "run", "--rm"]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += C.docker_mount_args() + [
        "-w", "/work",
        C.LL_IMAGE, "sta", "-no_init", "-exit",
        "tools/ro/ro_predict.tcl",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout[-3000:], res.stderr[-3000:])
        raise SystemExit(f"ro sta failed for {corner} ({mode})")
    return res.stdout + "\n===STDERR===\n" + res.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    os.makedirs(C.DATA, exist_ok=True)

    sels = [3] if args.smoke else [0, 1, 2, 3]
    rows = []
    for corner in C.CORNER_NAMES:
        cases_tcl = os.path.join(C.DATA, f"ro_cases_{corner}.tcl")
        gen_cases_tcl(cases_tcl, sels)
        raw, reps_by_mode = {}, {}
        for mode in ("line", "gate"):
            raw[mode] = run_ro(corner, cases_tcl, mode)
            reps_by_mode[mode] = parse_ro_report(raw[mode])
        with open(os.path.join(C.DATA, f"ro_report_{corner}.txt"), "w") as f:
            for mode in ("line", "gate"):
                f.write(f"######## ES_RO_MODE={mode}\n")
                f.write(raw[mode] + ("" if raw[mode].endswith("\n") else "\n"))
        for key in reps_by_mode["line"]:
            sel = int(key.split("=")[1])
            for ro in ("gen", "mat"):
                seg = {m: loop_delay_ns(reps_by_mode[m].get(key, {}).get(ro))
                       for m in ("line", "gate")}
                if None in seg.values():
                    t = None
                else:
                    t = seg["line"] + seg["gate"]
                row = {
                    "corner": corner,
                    "v_volt": dict((c[0], c[1]) for c in C.CORNERS)[corner],
                    "t_celsius": dict((c[0], c[2]) for c in C.CORNERS)[corner],
                    "canary": f"ro_{ro}",
                    "can_sel": sel,
                    "loop_delay_ns": round(t, 4) if t is not None else "",
                    "line_seg_ns": (round(seg["line"], 4)
                                    if seg["line"] is not None else ""),
                    "gate_seg_ns": (round(seg["gate"], 4)
                                    if seg["gate"] is not None else ""),
                    "startpoint": "u_ro_%s.u_gate.u_a3/X (nand_out)" % ro,
                    "endpoint": "u_ro_%s.u_gate.u_a3/X (nand_out)" % ro,
                }
                if t:
                    t_half = 2 * t  # ro_node period (posedge every loop traversal pair)
                    row["f_osc_mhz"] = round(1e3 / t_half, 3)
                    for win_sel, wcyc in C.WINDOW_CYCLES.items():
                        dur = wcyc * C.CLK_PERIOD_NS
                        cnt = int(dur / t_half)
                        row[f"count_win{win_sel}"] = cnt
                        row[f"sat_win{win_sel}"] = int(cnt > 65535)
                else:
                    row["f_osc_mhz"] = ""
                    for win_sel in C.WINDOW_CYCLES:
                        row[f"count_win{win_sel}"] = ""
                        row[f"sat_win{win_sel}"] = ""
                row.update({
                    "run_id": C.RUN_ID, "git_commit": C.GIT_COMMIT,
                    "librelane_image": C.LL_IMAGE, "pdk_rev": C.CIEL_PDK_REV,
                })
                rows.append(row)

    csv_path = os.path.join(C.DATA, "ro_predict.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(C.DATA, "ro_predict.json"), "w") as f:
        json.dump({"provenance": {
            "run_id": C.RUN_ID, "git_commit": C.GIT_COMMIT,
            "librelane_image": C.LL_IMAGE, "pdk_rev": C.CIEL_PDK_REV,
            "method": ("broken-loop extracted STA, full loop = line + gate "
                       "segment sum (see tools/ro/ro_predict.tcl)"),
        }, "rows": rows}, f, indent=1)
    print(f"wrote {csv_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
