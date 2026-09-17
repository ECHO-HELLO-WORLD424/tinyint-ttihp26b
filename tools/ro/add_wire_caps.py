#!/usr/bin/env python3
"""Add the extracted wire capacitance to an RO loop subcircuit.

The transient decks simulate the Magic spiceextraction, which is cell-level:
transistor-level cells with cell-internal parasitics but **no inter-cell wire
RC**.  This tool puts the missing lumped wire capacitance back, so its effect on
the ring period (and therefore on the window count) can be measured instead of
argued about:

  * every ring instance in the loop subcircuit is mapped to its SPEF instance
    (`X_0608_` <-> `_0608_`), and each (instance, pin) pair to its SPEF net;
  * the SPEF `*D_NET` capacitance of every net that touches the loop is summed
    onto the Magic net name that the loop subcircuit uses;
  * a copy of the loop subcircuit is written with one lumped capacitor per net
    inside the `.subckt` body (elements cannot be attached to subcircuit
    internal nodes from outside).

This is a **lumped-capacitance sensitivity variant**, not distributed-RC
signoff: the SPEF's own `*CAP`/`*RES` network is not rebuilt, so it bounds the
effect of the omitted interconnect rather than reproducing it.

Usage:
  add_wire_caps.py --loop-sp <in.sp> --spef <spef> --out <out.sp>
                   --netlist pins... [--scale 1.0] [--json out.json]
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import analyse_loop_rc as rc_mod  # noqa: E402


def subckt_pins(stdcell_spice, celltypes):
    """{celltype: [(pin, index)]} from the PDK stdcell subcircuit headers."""
    pins = {}
    for line in open(stdcell_spice):
        toks = line.split()
        if len(toks) > 3 and toks[0] == ".subckt" and toks[1] in celltypes:
            pins[toks[1]] = toks[2:]
    return pins


def build_map(loop_sp, spef, stdcell_spice):
    """{magic_net: (spef_cap_fF, [(inst, pin)])} for the loop's own nets."""
    name_map, nets = rc_mod.parse_spef(spef)
    num_to_name = dict(name_map)
    inst_of = {}
    for num, nm in name_map.items():
        inst_of.setdefault(nm, num)
    # SPEF instance -> {pin: net_name}
    inst_pin_net = {}
    for net in nets.values():
        for inst, pin in net["conns"]:
            inst_pin_net.setdefault(inst, {})[pin] = net["name"]

    lines = open(loop_sp).read().splitlines()
    celltypes = set()
    for line in lines:
        toks = line.split()
        if toks and toks[0].startswith("X"):
            celltypes.add(toks[-1])
    pins = subckt_pins(stdcell_spice, celltypes)

    out = {}
    unmapped = []
    for line in lines:
        toks = line.split()
        if not toks or not toks[0].startswith("X"):
            continue
        inst = toks[0]
        cell = toks[-1]
        nodes = toks[1:-1]
        plist = pins.get(cell)
        if not plist:
            unmapped.append((inst, cell, "no subckt pins"))
            continue
        num = inst_of.get(inst[1:] if inst.startswith("X") else inst)
        if num is None:
            unmapped.append((inst, cell, "instance not in SPEF"))
            continue
        pin_net = inst_pin_net.get(num, {})
        for pin, node in zip(plist, nodes):
            spef_net = pin_net.get(pin)
            if spef_net is None:
                unmapped.append((inst, cell, f"pin {pin} not in SPEF"))
                continue
            if node in ("SUP_VDD", "SUP_VSS", "0"):
                continue
            cap = nets[spef_net]["cap"]
            cur = out.setdefault(node, {})
            # Several pins of one Magic net map to the same SPEF net; keep one
            # entry per SPEF net so the capacitance is not counted twice.
            cur[spef_net] = cap
    per_net = {}
    for node, spef_caps in out.items():
        per_net[node] = dict(
            cap_fF=round(sum(spef_caps.values()), 4),
            spef_nets=sorted(spef_caps))
    return per_net, unmapped, len(nets)


def write_variant(loop_sp, out_sp, per_net, scale=1.0, subckt=None):
    lines = open(loop_sp).read().splitlines()
    if subckt is None:
        for line in lines:
            toks = line.split()
            if toks and toks[0] == ".subckt":
                subckt = toks[1]
                break
    out = []
    added = 0
    for line in lines:
        toks = line.split()
        if toks and toks[0] == ".ends":
            for i, (node, d) in enumerate(sorted(per_net.items())):
                cap_pf = d["cap_fF"] * 1e-3 * scale
                if cap_pf <= 0:
                    continue
                # The number is pF and MUST carry the `p` suffix: an
                # unsuffixed capacitor value is read as farads, so omitting it
                # inflates every injected capacitor by 10**12 (the revision-1
                # sensitivity decks stalled because of exactly that, not
                # because of the circuit).  See test_add_wire_caps.py.
                out.append(f"Cw{i} {node} 0 {cap_pf:.9g}p")
                added += 1
        out.append(line)
    with open(out_sp, "w") as fh:
        fh.write("\n".join(out) + "\n")
    return added, subckt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop-sp", required=True)
    ap.add_argument("--spef", required=True)
    ap.add_argument("--stdcell-spice", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--json", default=None)
    ap.add_argument("--scale", type=float, default=1.0)
    a = ap.parse_args()
    per_net, unmapped, n_spef_nets = build_map(a.loop_sp, a.spef,
                                               a.stdcell_spice)
    n, subckt = write_variant(a.loop_sp, a.out, per_net, a.scale)
    total = sum(d["cap_fF"] for d in per_net.values())
    summary = dict(loop_sp=a.loop_sp, out=a.out, subckt=subckt,
                   nets_with_caps=n, spef_nets=n_spef_nets,
                   total_wire_cap_fF=round(total, 3),
                   scale=a.scale, unmapped=unmapped[:10],
                   n_unmapped=len(unmapped),
                   per_net={k: v["cap_fF"] for k, v in per_net.items()})
    print(json.dumps({k: v for k, v in summary.items() if k != "per_net"},
                     indent=1))
    if a.json:
        json.dump(summary, open(a.json, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
