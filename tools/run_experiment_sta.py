#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Experiment-specific case-analyzed STA.

For every (segment-delay configuration, pattern class) in the predeclared
measurement matrix and every PVT corner, this flow case-analyzes the static
configuration state (cfg word, boot, started, freeze, rst_n, ena) and
reports the setup path from the runtime pattern-generator registers
(u_pat.lfsr/idx) to the one-shot DUT capture registers (result_reg).

The launch registers are resolved structurally inside OpenSTA (see
tools/sta/experiment_sta.tcl): every flip-flop in the DUT full-adder operand
fan-in cone that the static case analysis does not force to a constant. That
is 16 LFSR bits + 2 index flops; synthesis renames 8 of their Q nets, so the
former `*u_pat.lfsr*` / `*u_pat.idx*` net-name search silently dropped them.

Outputs (data/):
  sta_report_<corner>.txt   raw delimited OpenSTA report
  experiment_sta.csv        machine-readable table (acceptance artifact)
  experiment_sta.json       same rows + build provenance
  experiment_sta_launch_pins.json
                            resolved launch-pin list, the assertions the Tcl
                            flow enforced, and every case where the
                            unrestricted capture path is worse than the
                            runtime-state path (classified).

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
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

REPORT_FIELDS = {  # opensta report_checks -fields
    "full": "slew cap input net fanout",
}

# src/tpv_pattern_gen.v state: reg [15:0] lfsr + reg [1:0] idx.
EXPECTED_LAUNCH_PINS = 18

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


LAUNCH_PIN_RE = re.compile(
    r"^ES-LAUNCH-PIN\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s*$", re.M)
LAUNCH_SUMMARY_RE = re.compile(
    r"^ES-LAUNCH-PINS-OK\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", re.M)


def parse_launch_pins(text):
    """Resolved runtime launch pins reported by the Tcl flow.

    The Tcl flow resolves them structurally (DUT operand fan-in cone minus the
    case-analyzed static-configuration registers), asserts the 18-pin count,
    uniqueness and the 16-bit-LFSR + 2-bit-index-counter structure, and prints
    one ES-LAUNCH-PIN line per pin plus an ES-LAUNCH-PINS-OK summary. The
    driver re-asserts the count here so a silently reduced launch list cannot
    reach the dataset.
    """
    pins = []
    for m in LAUNCH_PIN_RE.finditer(text):
        pins.append({"pin": m.group(1), "role": m.group(2),
                     "q_net": m.group(3), "state_predecessors": int(m.group(4)),
                     "instance": m.group(1).rsplit("/", 1)[0]})
    summary = LAUNCH_SUMMARY_RE.search(text)
    if summary is None:
        raise RuntimeError("STA report has no ES-LAUNCH-PINS-OK summary")
    n_expected, n_named, n_static, n_seeds = (int(x) for x in summary.groups())
    if len(pins) != n_expected:
        raise RuntimeError(
            f"resolved {len(pins)} launch pins but the flow asserted {n_expected}")
    if n_expected != EXPECTED_LAUNCH_PINS:
        raise RuntimeError(
            f"STA flow resolved {n_expected} launch pins, expected "
            f"{EXPECTED_LAUNCH_PINS} (16 LFSR + 2 index flops in "
            f"src/tpv_pattern_gen.v)")
    roles = sorted(p["role"] for p in pins)
    want = sorted([f"lfsr{i}" for i in range(16)] + ["idx0", "idx1"])
    if roles != want:
        raise RuntimeError(f"launch-pin roles are {roles}, expected {want}")
    if len({p["pin"] for p in pins}) != len(pins):
        raise RuntimeError("launch pin list contains duplicates")
    return {"pins": pins, "named_anchors": n_named,
            "static_config_registers": n_static, "operand_seed_nets": n_seeds}


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
            lines.append('puts "CONTROL-MAX"')
            lines.append("report_checks -to $control_epins -path_delay max "
                         "-group_path_count 1 -format full_clock_expanded -corner nom")
            lines.append('puts "CONTROL-END"')
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return len(segs_list) * len(pats)


def run_sta(corner, cases_tcl, report_out, smoke=False,
            period_ns=C.CLK_PERIOD_NS, duty=C.CAPTURE_DUTY):
    """Run OpenSTA inside the LibreLane image (tool-identical to CI)."""
    libs = " ".join(
        C.PDK_INNER + "/" + rel for rel in C.CORNER_LIBS[corner])
    env = {
        "ES_LIBS": libs,
        "ES_PERIOD_NS": str(period_ns),
        "ES_DUTY": str(duty),
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
    open(report_out + ".stdout.log", "w").write(
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
    launch_by_corner = {}
    for corner in corners:
        cases_tcl = os.path.join(C.DATA, f"sta_cases_{corner}.tcl")
        n_cases = gen_cases_tcl(cases_tcl, segs_list, pats)
        report_out = os.path.join(C.DATA, f"sta_report_{corner}.txt")
        print(f"== corner {corner}: {n_cases} cases")
        text = run_sta(corner, cases_tcl, report_out, args.smoke)
        open(report_out, "w").write(text)
        cases = C.parse_case_report(text)
        if len(cases) != n_cases:
            raise RuntimeError(f"parsed {len(cases)}/{n_cases} cases")
        import re
        if re.search(r"(?:^Error:|ES WARNING)", text, re.M):
            raise RuntimeError("STA reported errors or missing static case nets; inspect raw report")
        launch = parse_launch_pins(text)
        launch_by_corner[corner] = launch
        role_by_instance = {p["instance"]: p["role"] for p in launch["pins"]}
        launch_q_nets = {p["q_net"] for p in launch["pins"]}
        controls = [C.parse_path_block(b) for b in
                    re.findall(r"CONTROL-MAX\n(.*?)CONTROL-END", text, re.S)]
        if len(controls) != n_cases or any(c is None for c in controls):
            raise RuntimeError("missing control timing reports")
        for case_index, (key, reps) in enumerate(cases.items()):
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
                "capture_duty": C.CAPTURE_DUTY,
            }
            if r2r and r2r.get("startpoint"):
                sp_inst = r2r["startpoint"].lstrip("\\")
                sp_net = qmap.get(sp_inst, "?")
                ep_net = qmap.get(r2r["endpoint"].lstrip("\\"), "?")
                ep_bit = (ep_net.split("[")[-1].rstrip("]")
                          if "result_reg" in ep_net else None)
                try:
                    ep_bit = int(ep_bit) if ep_bit is not None else None
                except ValueError:
                    ep_bit = None
                if ep_bit is not None:
                    # Record the operand TRANSITION (previous -> current) that
                    # exercises the longest carry chain to this capture bit,
                    # not a single static vector: the operands only change at
                    # the frame-boundary launch edge.
                    trans = C.sensitizing_transition(pat, ep_bit)
                    vec = trans["cur"] if trans else None
                    chain = trans["chain_stages"] if trans else None
                else:
                    vec, chain, trans = (None, None, None)
                row.update({
                    "startpoint": r2r["startpoint"],
                    "startpoint_reg": sp_net,
                    "startpoint_role": role_by_instance.get(sp_inst, ""),
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
                    "sensitizing_prev_vector": (
                        vector_str(trans["prev"]) if trans else ""),
                    "sensitizing_op_index": (
                        trans["op_index"] if trans else ""),
                    "sensitizing_chain_stages": chain,
                })
            else:
                row.update({
                    "startpoint": "", "startpoint_reg": "",
                    "startpoint_role": "",
                    "endpoint": "", "endpoint_reg": "", "endpoint_bit": "",
                    "path_delay_ns": "", "arrival_ns": "", "required_ns": "",
                    "slack_ns": "", "slack_met": "",
                    "predicted_fmax_mhz": "",
                    "sensitizing_vector": "(no runtime-sensitizable path)",
                    "sensitizing_prev_vector": "",
                    "sensitizing_op_index": "",
                    "sensitizing_chain_stages": "",
                })
            if glob:
                gsp = (glob.get("startpoint") or "").lstrip("\\")
                gsp_net = qmap.get(gsp, "")
                if gsp in role_by_instance:
                    gcls = "runtime_state"
                elif gsp_net in C.STATIC_CONFIG_NETS:
                    gcls = "static_configuration"
                else:
                    gcls = "control"
                row.update({
                    "global_startpoint": glob.get("startpoint", ""),
                    "global_startpoint_reg": gsp_net,
                    "global_startpoint_class": gcls,
                    "global_endpoint": glob.get("endpoint", ""),
                    "global_slack_ns": glob.get("slack_ns", ""),
                    "global_path_delay_ns": glob.get("path_delay_ns", ""),
                })
            control = controls[case_index]
            row.update({
                "control_startpoint": control["startpoint"],
                "control_endpoint": control["endpoint"],
                "control_slack_ns": control["slack_ns"],
                "run_id": C.RUN_ID,
                "git_commit": C.GIT_COMMIT,
                "librelane_image": C.LL_IMAGE,
                "pdk_rev": C.CIEL_PDK_REV,
            })
            rows.append(row)

    # The launch set is a property of the netlist, not of a corner: it must be
    # identical in every corner run.
    first_corner = corners[0]
    ref = launch_by_corner[first_corner]["pins"]
    for corner in corners[1:]:
        if launch_by_corner[corner]["pins"] != ref:
            raise RuntimeError(
                f"launch pins differ between {first_corner} and {corner}")

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
                "capture_duty": C.CAPTURE_DUTY,
        }, "rows": rows}, f, indent=1)
    print(f"wrote {csv_path} ({len(rows)} rows) and {json_path}")
    write_launch_pin_artifact(launch_by_corner, rows, corners)


def write_launch_pin_artifact(launch_by_corner, rows, corners):
    """Archive the resolved launch-pin list and the coverage cross-check.

    Reviewer-facing artifact for docs/rtl-freeze-checklist.md gate 4: which
    pins are launched from, how each was resolved, and every case where the
    unrestricted (ES-GLOBAL) capture path is worse than the runtime-state
    (ES-R2R) path, with the source classified.
    """
    first = corners[0]
    launch = launch_by_corner[first]
    netlist = C.netlist_path()
    spef = C.spef_path()
    script = os.path.join(C.REPO, "tools", "sta", "experiment_sta.tcl")
    gaps = []
    for r in rows:
        if not r.get("slack_ns") or not r.get("global_slack_ns"):
            continue
        try:
            gap = float(r["global_slack_ns"]) - float(r["slack_ns"])
        except (TypeError, ValueError):
            continue
        if gap < -1e-9:
            gaps.append({
                "corner": r["corner"], "cfg_word": r["cfg_word"],
                "pat_name": r["pat_name"],
                "seg": [r["seg0"], r["seg1"], r["seg2"], r["seg3"]],
                "r2r_slack_ns": r["slack_ns"],
                "global_slack_ns": r["global_slack_ns"],
                "gap_ns": round(gap, 6),
                "r2r_startpoint": r["startpoint"],
                "r2r_startpoint_role": r.get("startpoint_role", ""),
                "global_startpoint": r["global_startpoint"],
                "global_startpoint_reg": r["global_startpoint_reg"],
                "global_startpoint_class": r["global_startpoint_class"],
            })
    # Classification of the unrestricted (worst path to result_reg from any
    # startpoint) capture path in EVERY case, so a reviewer can see that no
    # static-configuration or control source is worse than the runtime set.
    classes = {}
    for r in rows:
        if not r.get("global_startpoint"):
            continue
        cls = r["global_startpoint_class"]
        slot = classes.setdefault(cls, {"cases": 0, "startpoints": {}})
        slot["cases"] += 1
        key = f"{r['global_startpoint']}({r['global_startpoint_reg']})"
        slot["startpoints"][key] = slot["startpoints"].get(key, 0) + 1
    sens = verify_sensitizing_transitions(rows)
    art = {
        "description": (
            "Runtime pattern-state launch pins for the experiment-specific "
            "case-analyzed STA, resolved structurally by "
            "tools/sta/experiment_sta.tcl (DUT full-adder operand fan-in cone "
            "minus the case-analyzed static-configuration registers), plus the "
            "restricted-vs-unrestricted coverage cross-check and the "
            "sensitizing-transition check for the reported critical paths."),
        "provenance": {
            "run_id": C.RUN_ID, "git_commit": C.GIT_COMMIT,
            "librelane_image": C.LL_IMAGE, "pdk_rev": C.CIEL_PDK_REV,
            "netlist": os.path.relpath(netlist, C.REPO),
            "netlist_sha256": sha256(netlist),
            "spef": os.path.relpath(spef, C.REPO),
            "spef_sha256": sha256(spef),
            "sta_script": os.path.relpath(script, C.REPO),
            "sta_script_sha256": sha256(script),
            "corners": corners,
        },
        "expected_launch_pins": EXPECTED_LAUNCH_PINS,
        "resolved_launch_pins": len(launch["pins"]),
        "synthesis_named_q_nets": launch["named_anchors"],
        "synthesis_renamed_q_nets": len(launch["pins"]) - launch["named_anchors"],
        "static_config_registers_in_operand_cone": (
            launch["static_config_registers"]),
        "operand_seed_nets": launch["operand_seed_nets"],
        "assertions": [
            "32 DUT full-adder operand nets (16 bits x a/b)",
            "18 launch pins = 16 LFSR + 2 index flops of src/tpv_pattern_gen.v",
            "launch pin list unique, every pin a sequential-cell output",
            "structural roles: single 16-node shift chain (head fed by "
            "feedback taps lfsr10/12/13/15 = x^16+x^14+x^13+x^11+1) plus a "
            "2-bit counter (idx0 has no state predecessor, idx1 depends only "
            "on idx0)",
            "every surviving u_pat.lfsr[N]/u_pat.idx[N] net name agrees with "
            "the structurally assigned role",
            "17 result_reg capture endpoints (unchanged)",
        ],
        "sensitizing_transition_check": sens,
        "unrestricted_capture_path_classes": classes,
        "launch_pins": launch["pins"],
        "per_corner_counts": {
            c: len(launch_by_corner[c]["pins"]) for c in corners},
        "global_worse_than_r2r_cases": gaps,
    }
    path = os.path.join(C.DATA, "experiment_sta_launch_pins.json")
    with open(path, "w") as f:
        json.dump(art, f, indent=1)
    print(f"wrote {path} ({len(launch['pins'])} launch pins, "
          f"{len(gaps)} global-worse-than-r2r cases, "
          f"{sens['sensitized_rows']}/{sens['checked_rows']} critical paths "
          f"checked against their operand transition)")


def verify_sensitizing_transitions(rows, n_ops=64):
    """Check each reported critical path against the transition that drives it.

    For every R2R row the flow records the operand pair (prev -> cur) around
    the operation with the longest carry chain to the captured bit. Here the
    recording is re-derived from the RTL decode model and checked:
      - the applied-operand sequence reproduces the recorded prev/cur at the
        recorded op index;
      - the launch register's operand fan-out at that op meets the bits that
        actually change between prev and cur (otherwise that transition cannot
        sensitize a path launched from that flop);
      - the recorded carry-chain length is the one the cur vector produces.
    A path whose transition does not move an operand bit the launch register
    drives would be an STA-only structural path, not an exercised one.
    """
    def parse(vec):
        m = re.match(r"a=0x([0-9A-Fa-f]+),b=0x([0-9A-Fa-f]+),cin=(\d)",
                     vec or "")
        if not m:
            return None
        return (int(m.group(1), 16), int(m.group(2), 16), int(m.group(3)))

    def bits_of(vec):
        out = {f"a[{i}]": (vec[0] >> i) & 1 for i in range(16)}
        out.update({f"b[{i}]": (vec[1] >> i) & 1 for i in range(16)})
        out["cin"] = vec[2]
        return out

    checked = sensitized = 0
    unsensitized = []
    per_role = {}
    for r in rows:
        if not r.get("startpoint_role") or not r.get("sensitizing_op_index"):
            continue
        checked += 1
        sel = int(r["pattern"])
        op = int(r["sensitizing_op_index"])
        vecs = C.pattern_vectors(sel, n_ops)
        states = C.pattern_states(sel, n_ops)
        prev, cur = parse(r["sensitizing_prev_vector"]), parse(
            r["sensitizing_vector"])
        if prev is None or cur is None or vecs[op] != cur or vecs[op - 1] != prev:
            raise RuntimeError(
                f"sensitizing transition not reproducible for "
                f"{r['corner']}/{r['cfg_word']}: op {op} {prev} -> {cur}")
        if C.carry_chain_length(cur[0], cur[1], cur[2],
                                r["endpoint_bit"]) != r["sensitizing_chain_stages"]:
            raise RuntimeError(
                f"carry-chain length mismatch for {r['corner']}/{r['cfg_word']}")
        role = r["startpoint_role"]
        key = (f"lfsr[{role[4:]}]" if role.startswith("lfsr")
               else f"idx[{role[3:]}]")
        influence = C.operand_bit_influence(sel, *states[op])[key]
        pb, cb = bits_of(prev), bits_of(cur)
        changed = {k for k in cb if cb[k] != pb[k]}
        hit = sorted(set(influence) & changed)
        if hit:
            sensitized += 1
        else:
            unsensitized.append({
                "corner": r["corner"], "cfg_word": r["cfg_word"],
                "pat_name": r["pat_name"], "role": role,
                "launch_operand_bits": sorted(influence),
                "changed_operand_bits": sorted(changed)})
        slot = per_role.setdefault(role, {
            "rows": 0, "launch_operand_bits": sorted(influence),
            "max_carry_chain_stages": 0,
            "endpoints": {}, "launched_bits_that_change": {}})
        slot["rows"] += 1
        slot["max_carry_chain_stages"] = max(
            slot["max_carry_chain_stages"], r["sensitizing_chain_stages"])
        ep = str(r["endpoint_reg"])
        slot["endpoints"][ep] = slot["endpoints"].get(ep, 0) + 1
        for b in hit:
            slot["launched_bits_that_change"][b] = \
                slot["launched_bits_that_change"].get(b, 0) + 1
    if unsensitized:
        raise RuntimeError(
            f"{len(unsensitized)} critical paths are not sensitized by the "
            f"recorded operand transition: {unsensitized[:3]}")
    return {
        "method": ("operand transition (prev -> cur) at the frame-boundary "
                   "launch edge, re-derived from tools/common.py's RTL decode "
                   "model and checked against the launch register's operand "
                   "fan-out"),
        "launch_edge": ("rising clk edge at frame_cnt==FRAME_LAST with "
                        "load=1; pattern registers advance, capture_pending "
                        "is set"),
        "capture_edge": ("falling clk edge immediately after that rising edge "
                         "(clock HIGH time = measurement aperture)"),
        "n_ops_searched": n_ops,
        "checked_rows": checked,
        "sensitized_rows": sensitized,
        "unsensitized_rows": unsensitized,
        "per_startpoint_role": per_role,
    }


if __name__ == "__main__":
    main()
