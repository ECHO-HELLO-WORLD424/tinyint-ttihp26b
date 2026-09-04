#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""RO canary loop-delay prediction driver (P1.3).

For every PVT corner and canary tap selection (can_sel 0..3), measures the
extracted loop delay of both canary ring oscillators (broken-loop STA with
SPEF parasitics) and derives:

  f_osc [MHz]      = 1 / (2 * T_loop)
  count[win]       = floor(window_cycles * T_clk / (2 * T_loop))
  overflow flag    = count > 1023 (10-bit edge counters)

Outputs data/ro_predict.csv + .json, plus data/ro_report_<corner>.txt raw.

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
    lines = []
    for sel in sels:
        lines.append(f'puts "==ROCASE sel={sel}"')
        lines.append(f"ro_case_net {(sel) & 1} {{can_sel[0]}}")
        lines.append(f"ro_case_net {(sel >> 1) & 1} {{can_sel[1]}}")
        lines.append('puts "RO-GEN"')
        lines.append(
            "set_max_delay 1000 -from [get_pins {u_ro_gen.u_gate.u_a3/X}] "
            "-to [get_pins {u_ro_gen.u_gate.u_a2/A}]")
        lines.append(
            "report_checks -from [get_pins {u_ro_gen.u_gate.u_a3/X}] "
            "-to [get_pins {u_ro_gen.u_gate.u_a2/A}] -path_delay max "
            "-group_path_count 1 -fields {slew cap} "
            "-format full_clock_expanded -corner nom")
        lines.append('puts "RO-MAT"')
        lines.append(
            "set_max_delay 1000 -from [get_pins {u_ro_mat.u_gate.u_a3/X}] "
            "-to [get_pins {u_ro_mat.u_gate.u_a2/A}]")
        lines.append(
            "report_checks -from [get_pins {u_ro_mat.u_gate.u_a3/X}] "
            "-to [get_pins {u_ro_mat.u_gate.u_a2/A}] -path_delay max "
            "-group_path_count 1 -fields {slew cap} "
            "-format full_clock_expanded -corner nom")
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
    # unconstrained comb path: arrival at the -to pin IS the loop delay
    return block["arrival_ns"]


def run_ro(corner, cases_tcl):
    libs = " ".join(
        C.PDK_INNER + "/" + rel for rel in C.CORNER_LIBS[corner])
    env = {
        "ES_LIBS": libs,
        "ES_NETLIST": C.netlist_path().replace(C.REPO, "/work"),
        "ES_SPEF": C.spef_path().replace(C.REPO, "/work"),
        "ES_CASES_TCL": cases_tcl.replace(C.REPO, "/work"),
    }
    cmd = [
        "docker", "exec", "amazing_robinson", "docker", "run", "--rm",
        "-v", "/workspaces/tinyint-ttihp26b:/work", "-w", "/work",
        "-v", f"{C.PDK_HOST}:/pdk:ro",
        C.LL_IMAGE, "sta", "-no_init", "-exit",
        "tools/ro/ro_predict.tcl",
    ]
    for k, v in env.items():
        cmd[5:5] = ["-e", f"{k}={v}"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(C.DATA, f"ro_report_{corner}.txt"), "w").write(
        res.stdout + "\n===STDERR===\n" + res.stderr)
    if res.returncode != 0:
        print(res.stdout[-3000:], res.stderr[-3000:])
        raise SystemExit(f"ro sta failed for {corner}")
    return res.stdout


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
        text = run_ro(corner, cases_tcl)
        cases = parse_ro_report(text)
        for key, reps in cases.items():
            sel = int(key.split("=")[1])
            for ro in ("gen", "mat"):
                t = loop_delay_ns(reps.get(ro))
                row = {
                    "corner": corner,
                    "v_volt": dict((c[0], c[1]) for c in C.CORNERS)[corner],
                    "t_celsius": dict((c[0], c[2]) for c in C.CORNERS)[corner],
                    "canary": f"ro_{ro}",
                    "can_sel": sel,
                    "loop_delay_ns": round(t, 4) if t is not None else "",
                    "startpoint": (reps.get(ro) or {}).get("startpoint", ""),
                    "endpoint": (reps.get(ro) or {}).get("endpoint", ""),
                }
                if t:
                    t_half = 2 * t  # ro_node period (posedge every loop traversal pair)
                    row["f_osc_mhz"] = round(1e3 / t_half, 3)
                    for win_sel, wcyc in C.WINDOW_CYCLES.items():
                        dur = wcyc * C.CLK_PERIOD_NS
                        cnt = int(dur / t_half)
                        row[f"count_win{win_sel}"] = cnt
                        row[f"sat_win{win_sel}"] = int(cnt > 1023)
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
            "method": "broken-loop extracted STA (see tools/ro/ro_predict.tcl)",
        }, "rows": rows}, f, indent=1)
    print(f"wrote {csv_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
