#!/usr/bin/env python3
"""Quantify the interconnect capacitance the cell-level RO decks omit.

`run_ro_count_case.py` simulates the Magic spiceextraction of the ring plus its
counter: transistor-level cells (with cell-internal parasitics) and no
inter-cell wire RC.  The post-route SPEF has that missing piece.  This tool
compares the two so the omission can be bounded instead of merely admitted:

  * every net that touches a ring instance is looked up in the SPEF;
  * its extracted capacitance (`*D_NET <net> <cap>`) is summed;
  * the same sum is formed for the whole design, and for the ring's share of it;
  * the ring's total load capacitance is estimated from the Liberty input-pin
    capacitances of the cells the ring nets drive, so the wire fraction can be
    expressed as a percentage of the load the transient actually sees.

Usage:
  analyse_loop_rc.py --spef <spef> --loops runs/count-loops --liberty <lib>
                     [--outdir data/safe10/freeze] [--json out.json]
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def parse_spef(path):
    """-> (name_map, nets); net caps are converted to fF (SPEF C_UNIT is pF)."""
    name_map = {}
    nets = {}
    cur = None
    section = None
    with open(path, errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("*NAME_MAP"):
                section = "map"
                continue
            if line.startswith("*D_NET"):
                m = re.match(r"\*D_NET\s+(\S+)\s+(\S+)", line)
                if m:
                    cur = dict(name=m.group(1), cap=float(m.group(2)) * 1000.0,
                               conns=[])
                    nets[cur["name"]] = cur
                section = "net"
                continue
            if line.startswith("*CONN"):
                section = "conn"
                continue
            if line.startswith("*CAP"):
                section = "cap"
                continue
            if line.startswith("*RES"):
                section = "res"
                continue
            if line.startswith("*END"):
                cur = None
                section = None
                continue
            if section == "map":
                m = re.match(r"\*(\d+)\s+(\S+)\s*$", line)
                if m:
                    name_map[m.group(1)] = m.group(2)
            elif section == "conn" and cur is not None:
                m = re.match(r"\*I\s+(\S+?):(\S+)", line.strip())
                if m:
                    inst = m.group(1).lstrip("*")
                    cur["conns"].append((inst, m.group(2)))
    return name_map, nets


def parse_liberty_pin_caps(path):
    """{cell: {pin: capacitance_fF}} from a Liberty file."""
    caps = {}
    cell = None
    pin = None
    with open(path, errors="replace") as fh:
        for line in fh:
            s = line.strip()
            m = re.match(r'cell\s*\(\s*"?([\w.]+)"?\s*\)', s)
            if m:
                cell = m.group(1)
                caps[cell] = {}
                pin = None
                continue
            m = re.match(r'pin\s*\(\s*"?([\w.]+)"?\s*\)', s)
            if m:
                pin = m.group(1)
                continue
            m = re.match(r"capacitance\s*:\s*([0-9.eE+-]+)", s)
            if m and cell and pin:
                caps[cell][pin] = float(m.group(1)) * 1e3    # pF -> fF
    return caps


def parse_loop_instances(loop_sp):
    """Ring instance names and the subcircuit's internal net names."""
    insts = []
    nets = set()
    for line in open(loop_sp):
        toks = line.split()
        if not toks or not toks[0].startswith("X"):
            continue
        insts.append(toks[0])
    return insts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spef", required=True)
    ap.add_argument("--loops", required=True,
                    help="directory with <canary>_sel<N>_loop.sp")
    ap.add_argument("--liberty", required=True)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    name_map, nets = parse_spef(a.spef)
    pin_caps = parse_liberty_pin_caps(a.liberty)
    total_cap = sum(n["cap"] for n in nets.values())

    # Instance name in the Magic extraction is `X<name>`; the SPEF name map has
    # `<name>`.  Build the reverse index: SPEF instance -> nets it touches.
    inst_nets = {}
    for net in nets.values():
        for inst, pin in net["conns"]:
            inst_nets.setdefault(inst, []).append(net["name"])
    by_name = {}
    for num, nm in name_map.items():
        by_name[nm] = num

    rows = []
    for fn in sorted(os.listdir(a.loops)):
        if not fn.endswith("_loop.sp"):
            continue
        canary_sel = fn[:-len("_loop.sp")]
        insts = parse_loop_instances(os.path.join(a.loops, fn))
        ring_nets = set()
        missing = []
        for inst in insts:
            nm = inst[1:] if inst.startswith("X") else inst
            num = by_name.get(nm)
            if num is None:
                missing.append(inst)
                continue
            ring_nets.update(inst_nets.get(num, []))
        wire = sum(nets[n]["cap"] for n in ring_nets)
        # Load estimate: input pins of the cells in the loop, from Liberty.
        load = 0.0
        n_pins = 0
        for line in open(os.path.join(a.loops, fn)):
            toks = line.split()
            if not toks or not toks[0].startswith("X"):
                continue
            ctype = toks[-1]
            pins = pin_caps.get(ctype) or {}
            # Count the subcircuit's input pins only (last pin is the output).
            for pin, c in pins.items():
                if pin.upper() in ("A", "B", "C", "A0", "A1", "A2", "A3",
                                   "S", "CI", "D", "CLK", "RESET_B", "RESET"):
                    load += c
                    n_pins += 1
        rows.append(dict(loop=canary_sel, instances=len(insts),
                         nets=len(ring_nets),
                         ring_wire_cap_fF=round(wire, 4),
                         design_wire_cap_fF=round(total_cap, 4),
                         ring_share_of_design_pct=round(
                             100.0 * wire / total_cap, 3) if total_cap else None,
                         liberty_input_cap_fF=round(load, 4),
                         wire_over_load_pct=round(100.0 * wire / load, 3)
                         if load else None,
                         instances_missing_from_spef=missing[:5],
                         n_missing=len(missing)))
    out = dict(spef=a.spef, liberty=a.liberty, loops=a.loops,
               design_nets=len(nets), design_wire_cap_fF=round(total_cap, 4),
               per_loop=rows)
    print(json.dumps(out, indent=1)[:4000])
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
