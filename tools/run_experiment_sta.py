#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Experiment-specific case-analyzed STA (PRE_SILICON_ACTION_PLAN P0.2).

For every (segment-delay configuration, pattern class) in the predeclared
measurement matrix and every PVT corner, this flow case-analyzes the static
configuration state (cfg word, boot, oe_cnt, started, freeze, rst_n, ena) and
reports the setup path from the runtime pattern-generator registers
(u_pat.lfsr/idx) to the one-shot DUT capture registers (result_reg).

Outputs (data/):
  sta_report_<corner>.txt   raw delimited OpenSTA report
  experiment_sta.csv        machine-readable table (acceptance artifact)
  experiment_sta.json       same rows + build provenance

The globally worst signoff path is NOT reported here (see the LibreLane
STAPostPNR reports); ES-GLOBAL columns give the worst path to result_reg from
any startpoint under the same case analysis, as a cross-check that the
runtime path dominates the capture boundary.

Run (host): python3 tools/run_experiment_sta.py [--corner NAME] [--smoke]
Requires docker (via the devcontainer's docker exec) with the LibreLane image.
"""

import argparse
import csv
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

REPORT_FIELDS = {  # opensta report_checks -fields
    "full": "slew cap input net fanout",
}

CFG_LAYOUT = {
    "seg0": (0, 2), "seg1": (2, 2), "seg2": (4, 2), "seg3": (6, 2),
    "pat": (8, 2), "cansel": (10, 2), "winsel": (12, 2),
    "force_can": (14, 1), "force_err": (15, 1),
}


def cfg_word(segs, pat, cansel=0, winsel=0, force_can=0, force_err=0):
    return ((segs[0] & 3) | ((segs[1] & 3) << 2) | ((segs[2] & 3) << 4)
            | ((segs[3] & 3) << 6) | ((pat & 3) << 8) | ((cansel & 3) << 10)
            | ((winsel & 3) << 12) | (force_can << 14) | (force_err << 15))


def netlist_q_map(netlist_path):
    """instance name -> Q net name for every library FF in the netlist."""
    import re
    inst_re = re.compile(r"(sg13g2_\w+)\s+(\\?\S+)\s*\((.*?)\);", re.S)
    q_re = re.compile(r"\.Q\\?\(\s*\\?([^)\s]+)")
    qmap = {}
    src = open(netlist_path).read()
    for cell, inst, body in inst_re.findall(src):
        m = q_re.search(body)
        if m:
            qmap[inst.lstrip("\\")] = m.group(1).lstrip("\\")
    return qmap


def gen_cases_tcl(path, segs_list, pats):
    lines = []
    for segs in segs_list:
        for pat in pats:
            word = cfg_word(segs, pat)
            key = "seg{}{}{}{}-pat{}".format(*segs, pat)
            lines.append(f'puts "==CASE {key}"')
            for bit in range(16):
                # Yosys preserved cfg[10]/cfg[11] as the named wires
                # can_sel[0]/can_sel[1]; case those names (no effect on the
                # DUT path -- can_sel only feeds the RO loops and readout).
                net = f"can_sel[{bit - 10}]" if bit in (10, 11) else f"cfg[{bit}]"
                lines.append(
                    f"es_case_net {(word >> bit) & 1} {{{net}}}")
            lines.append('puts "ES-R2R"')
            lines.append(
                "report_checks -from $spins -to $epins -path_delay max "
                "-group_path_count 1 -endpoint_path_count 1 "
                f"-fields {{{REPORT_FIELDS['full']}}} "
                "-format full_clock_expanded -corner nom")
            lines.append('puts "ES-GLOBAL"')
            lines.append(
                "report_checks -to $epins -path_delay max "
                "-group_path_count 1 -endpoint_path_count 1 "
                f"-fields {{{REPORT_FIELDS['full']}}} "
                "-format full_clock_expanded -corner nom")
            lines.append('puts "ES-END"')
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return len(segs_list) * len(pats)


def run_sta(corner, cases_tcl, report_out, smoke=False):
    """Run OpenSTA inside the LibreLane image (tool-identical to CI)."""
    libs = " ".join(
        C.PDK_INNER + "/" + rel for rel in C.CORNER_LIBS[corner])
    env = {
        "ES_LIBS": libs,
        "ES_NETLIST": C.netlist_path().replace(C.REPO, "/work"),
        "ES_SPEF": C.spef_path().replace(C.REPO, "/work"),
        "ES_SDC": "/work/src/pnr.sdc",
        "ES_CASES_TCL": cases_tcl.replace(C.REPO, "/work"),
        "ES_REPORT": report_out.replace(C.REPO, "/work"),
    }
    cmd = C.docker_prefix() + ["docker", "run", "--rm"]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += C.docker_mount_args() + [
        "-w", "/work",
        C.LL_IMAGE, "sta", "-no_init", "-exit",
        "tools/sta/experiment_sta.tcl",
    ]
    print("+", " ".join(cmd[:12]), "...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    # OpenSTA prints the case reports on stdout (delimited by ES markers);
    # keep both streams on disk for provenance/debugging.
    open(os.path.join(C.DATA, f"sta_stdout_{corner}.log"), "w").write(
        res.stdout + "\n===STDERR===\n" + res.stderr)
    if res.returncode != 0:
        print(res.stdout[-4000:])
        print(res.stderr[-4000:])
        raise SystemExit(f"openroad failed for corner {corner}")
    return res.stdout


def vector_str(vec):
    a, b, cin = vec
    return f"a=0x{a:04X},b=0x{b:04X},cin={cin}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corner", default=None, help="single corner name")
    ap.add_argument("--smoke", action="store_true",
                    help="one config/pattern only, to validate the flow")
    args = ap.parse_args()

    os.makedirs(C.DATA, exist_ok=True)
    corners = [args.corner] if args.corner else C.CORNER_NAMES
    qmap = netlist_q_map(C.netlist_path())

    segs_list = C.SEG_CONFIGS[:1] if args.smoke else C.SEG_CONFIGS
    pats = C.PATTERNS[:1] if args.smoke else C.PATTERNS

    rows = []
    for corner in corners:
        cases_tcl = os.path.join(C.DATA, f"sta_cases_{corner}.tcl")
        n_cases = gen_cases_tcl(cases_tcl, segs_list, pats)
        report_out = os.path.join(C.DATA, f"sta_report_{corner}.txt")
        print(f"== corner {corner}: {n_cases} cases")
        text = run_sta(corner, cases_tcl, report_out, args.smoke)
        open(report_out, "w").write(text)
        cases = C.parse_case_report(text)
        if len(cases) != n_cases:
            print(f"  WARNING: parsed {len(cases)}/{n_cases} cases")
        for key, reps in cases.items():
            seg_part, pat_part = key.split("-pat")
            segs = tuple(int(x) for x in seg_part[len("seg"):])
            pat = int(pat_part)
            word = cfg_word(segs, pat)
            r2r = reps.get("r2r")
            glob = reps.get("global")
            row = {
                "corner": corner,
                "v_volt": dict((c[0], c[1]) for c in C.CORNERS)[corner],
                "t_celsius": dict((c[0], c[2]) for c in C.CORNERS)[corner],
                "pattern": pat,
                "pat_name": C.PATTERN_NAMES[pat],
                "seg0": segs[0], "seg1": segs[1], "seg2": segs[2],
                "seg3": segs[3],
                "cfg_word": f"0x{word:04X}",
                "clk_period_ns": C.CLK_PERIOD_NS,
            }
            if r2r and r2r.get("startpoint"):
                sp_net = qmap.get(r2r["startpoint"].lstrip("\\"), "?")
                ep_net = qmap.get(r2r["endpoint"].lstrip("\\"), "?")
                ep_bit = (ep_net.split("[")[-1].rstrip("]")
                          if "result_reg" in ep_net else None)
                try:
                    ep_bit = int(ep_bit) if ep_bit is not None else None
                except ValueError:
                    ep_bit = None
                if ep_bit is not None:
                    vec, chain = C.sensitizing_vector(pat, ep_bit)
                else:
                    vec, chain = (None, None)
                row.update({
                    "startpoint": r2r["startpoint"],
                    "startpoint_reg": sp_net,
                    "endpoint": r2r["endpoint"],
                    "endpoint_reg": ep_net,
                    "endpoint_bit": ep_bit,
                    "path_delay_ns": r2r.get("path_delay_ns"),
                    "arrival_ns": r2r.get("arrival_ns"),
                    "required_ns": r2r.get("required_ns"),
                    "slack_ns": r2r.get("slack_ns"),
                    "slack_met": r2r.get("slack_met"),
                    "predicted_fmax_mhz": (
                        round(C.predicted_fmax_mhz(r2r["slack_ns"]), 3)
                        if r2r.get("slack_ns") is not None else None),
                    "sensitizing_vector": vector_str(vec) if vec else "",
                    "sensitizing_chain_stages": chain,
                })
            else:
                row.update({
                    "startpoint": "", "startpoint_reg": "",
                    "endpoint": "", "endpoint_reg": "", "endpoint_bit": "",
                    "path_delay_ns": "", "arrival_ns": "", "required_ns": "",
                    "slack_ns": "", "slack_met": "",
                    "predicted_fmax_mhz": "",
                    "sensitizing_vector": "(no runtime-sensitizable path)",
                    "sensitizing_chain_stages": "",
                })
            if glob:
                row.update({
                    "global_startpoint": glob.get("startpoint", ""),
                    "global_startpoint_reg": qmap.get(
                        (glob.get("startpoint") or "").lstrip("\\"), ""),
                    "global_endpoint": glob.get("endpoint", ""),
                    "global_slack_ns": glob.get("slack_ns", ""),
                    "global_path_delay_ns": glob.get("path_delay_ns", ""),
                })
            row.update({
                "run_id": C.RUN_ID,
                "git_commit": C.GIT_COMMIT,
                "librelane_image": C.LL_IMAGE,
                "pdk_rev": C.CIEL_PDK_REV,
            })
            rows.append(row)

    csv_path = os.path.join(C.DATA, "experiment_sta.csv")
    if rows:
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    json_path = os.path.join(C.DATA, "experiment_sta.json")
    with open(json_path, "w") as f:
        json.dump({"provenance": {
            "run_id": C.RUN_ID, "git_commit": C.GIT_COMMIT,
            "librelane_image": C.LL_IMAGE, "pdk_rev": C.CIEL_PDK_REV,
            "clk_period_ns": C.CLK_PERIOD_NS,
        }, "rows": rows}, f, indent=1)
    print(f"wrote {csv_path} ({len(rows)} rows) and {json_path}")


if __name__ == "__main__":
    main()
