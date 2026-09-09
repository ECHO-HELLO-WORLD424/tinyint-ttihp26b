#!/usr/bin/env python3
"""Extract one RO canary loop from the flat, extracted top-level SPICE netlist.

The extracted netlist (Magic spiceextraction) is flat: every standard cell is
an X-instance at the top level with escaped net names, so both ring oscillators
are directly visible as cycles over those nets.  Simulating the whole 1x1 chip
(1637 non-filler instances, transistor level) is unnecessary for an f_osc
measurement; the ring plus its enable gate and the first counter flop is enough.

The loop is traced explicitly: start at the NAND-gate output (the `nand_out` /
`ro_node` net), then repeatedly follow the single cell that drives the current
net until the traversal returns to the start.  Every cell on that path is a
member of the ring.  Inputs of ring cells that are not driven by another ring
cell are the ring's external control pins: en, mask and the mux `sel` bits.
Those are turned into subcircuit ports so a deck can drive them exactly.

Usage:  extract_ro.py <netlist> <outdir>
"""

import json
import os
import re
import sys
from collections import defaultdict

ESCAPE = re.compile(r"\\(.)")
SPECIAL = set("[]()/.:$#@!%^&*+-=~`|<>?',;\"")


def unescape(tok):
    return ESCAPE.sub(r"\1", tok)


def escape(tok):
    return "".join(("\\" + ch) if ch in SPECIAL else ch for ch in tok)


def parse_netlist(path):
    subckts = {}
    toplevel = []
    top_name = None
    cur = None
    pending = None
    with open(path) as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("*"):
                continue
            if stripped.startswith("+"):
                if pending is not None:
                    pending += " " + stripped[1:].strip()
                continue
            if pending is not None:
                _consume(pending, cur, subckts, toplevel)
                pending = None
            if stripped.lower().startswith(".subckt"):
                toks = stripped.split()
                cur = toks[1]
                top_name = cur
                pending = stripped
                continue
            if stripped.lower().startswith(".ends"):
                pending = None
                cur = None
                continue
            pending = stripped
    if pending is not None:
        _consume(pending, cur, subckts, toplevel)
    return subckts, toplevel, top_name


def _consume(line, cur, subckts, toplevel):
    if not line:
        return
    low = line.lower()
    if low.startswith(".subckt"):
        toks = line.split()
        subckts[toks[1]] = {"ports": toks[2:], "lines": []}
        return
    if low.startswith(".ends"):
        return
    if cur is None:
        toplevel.append(line)
    else:
        subckts[cur]["lines"].append(line)


def parse_element(line):
    toks = line.split()
    if not toks or not toks[0].upper().startswith("X"):
        return None
    inst = toks[0]
    nodes = [unescape(t) for t in toks[1:-1]]
    cell = toks[-1]
    return inst, unescape(inst), nodes, cell


def build_graph(lines):
    """Build the cell graph, canonicalising net names.

    In the flat extracted netlist a net is named after the output pin of its
    driver (e.g. `u_ro_gen.u_line.g_inv[0].u_inv._cell/A` is the net driven by
    `Xu_ro_gen.u_line.g_inv[0].u_inv._cell`).  Those names can also appear as
    an input pin name of another cell, so a plain name lookup can attach a
    driver to the wrong net.  Every net is therefore canonicalised to the
    (cell, output-pin) pair that actually drives it.
    """
    elements = {}
    raw = []
    for line in lines:
        p = parse_element(line)
        if not p:
            continue
        _, inst_u, nodes, cell = p
        if cell.lower().startswith(("sg13g2_fill", "sg13g2_decap")):
            continue
        elements[inst_u] = (nodes, cell)
        raw.append((inst_u, nodes, cell))
    # canonical net id: index of the driving cell, or the literal name
    canon = {}
    for inst, nodes, cell in raw:
        if nodes:
            canon[nodes[0]] = ("drv", inst)
    for inst, nodes, cell in raw:
        for n in nodes:
            if n not in canon and n not in ("VPWR", "VGND"):
                canon[n] = ("ext", n)
    drivers = defaultdict(list)
    loads = defaultdict(list)
    for inst, nodes, cell in raw:
        if not nodes:
            continue
        drivers[canon[nodes[0]]].append(inst)
        for n in nodes[1:]:
            loads[canon.get(n, ("ext", n))].append(inst)
    return elements, drivers, loads, canon


def find_ring(elements, drivers, canon, start_cell, root_prefix, can_sel):
    """Cells reachable from the loop node's driver over ring-coloured edges.

    Ring-coloured means: the net is driven by another cell of the same RO.
    This collects the ring together with the tap mux and the gate cells whose
    other inputs are external control pins.
    """
    def local(cell):
        return cell.startswith(root_prefix)

    ring = {start_cell}
    stack = [start_cell]
    while stack:
        cell = stack.pop()
        nodes, _ = elements[cell]
        for pin in nodes[1:]:
            if pin in ("VPWR", "VGND"):
                continue
            for d in drivers.get(canon.get(pin, ("ext", pin)), []):
                if local(d) and d not in ring:
                    ring.add(d)
                    stack.append(d)
    return sorted(ring)


def main():
    netlist, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    subckts, toplevel, top_name = parse_netlist(netlist)
    if top_name in subckts and subckts[top_name]["lines"]:
        toplevel = toplevel + subckts[top_name]["lines"]
    elements, drivers, loads, canon = build_graph(toplevel)

    report = {"netlist": os.path.basename(netlist), "top_subckt": top_name,
              "instances_total": len(elements), "canaries": {}}
    for canary in ("ro_gen", "ro_mat"):
      for can_sel in range(4):
        gate_out = f"_1351_/CLK" if canary == "ro_gen" else f"_1367_/CLK"
        start_cell = [d for d in drivers.get(canon.get(gate_out), [])
                      if d.startswith(("Xu_ro_gen.", "Xu_ro_mat."))]
        if len(start_cell) != 1:
            raise RuntimeError(f"{gate_out}: expected 1 driver, got {start_cell}")
        start_cell = start_cell[0]
        ring = find_ring(elements, drivers, canon, start_cell,
                         ("Xu_ro_gen.", "Xu_ro_mat."), can_sel)
        ext = {}
        # The counter flop clocked directly by the ring node is a real
        # capacitive load on the loop and is part of the extracted netlist;
        # include it (its D/RESET_B pins become ports, driven in the deck).
        loads_ring = [l for l in loads.get(canon.get(gate_out), [])
                      if not l.startswith(("Xu_ro_gen.", "Xu_ro_mat."))]
        for l in loads_ring:
            nodes, ctype = elements[l]
            for pin in nodes[1:]:
                if pin in ("VPWR", "VGND"):
                    continue
                if not drivers.get(canon.get(pin, ("ext", pin))):
                    ext.setdefault(pin, []).append(l)
        ring = sorted(set(ring) | set(loads_ring))
        # Any input pin of a ring cell that is not driven by another cell
        # inside the subcircuit must become a port.  Otherwise it is left
        # floating (its real driver was excluded from the subtree) and the
        # operating point does not converge.
        for cell in ring:
            nodes, ctype = elements[cell]
            for pin in nodes[1:]:
                if pin in ("VPWR", "VGND"):
                    continue
                drv = [d for d in drivers.get(canon.get(pin, ("ext", pin)), [])
                       if d in ring]
                if not drv:
                    ext.setdefault(pin, []).append(cell)
        print(f"\n{canary} sel{can_sel}: ring cells={len(ring)}")
        print(f"  loop node: {gate_out}")
        print(f"  external control pins ({len(ext)}):")
        for pin, users in sorted(ext.items()):
            print(f"    {pin:45s} -> {', '.join(users)}")
        print(f"  non-ring loads on loop node: {loads_ring}")
        report["canaries"][f"{canary}_sel{can_sel}"] = {
            "canary": canary,
            "can_sel": can_sel,
            "loop_node": gate_out,
            "ring_cells": ring,
            "n_ring_cells": len(ring),
            "external_pins": {k: v for k, v in sorted(ext.items())},
            "loop_node_loads": loads_ring,
        }
        # Drop ports that are simply undriven stubs (unselected mux branches,
        # tie-cell outputs): tie them to ground inside the subcircuit instead
        # of exposing them.  Keep real control pins as ports.
        dropped = {}
        for pin, users in list(ext.items()):
            if any(u.rsplit(".", 1)[-1].startswith(("u_m0_", "u_m1_", "u_x1_",
                                                    "u_a1_"))
                   for u in users):
                dropped[pin] = "VGND"
                del ext[pin]
        ports = sorted(set(ext.keys()) | {"VPWR", "VGND"})
        # Rename every node that the subcircuit sees from outside so it cannot
        # collide with the flat top-level net names of the extracted netlist
        # (a subcircuit port and a top-level net with the same name are two
        # different nodes; supplies would silently float, and control pins
        # would never be driven).
        portmap = {"VPWR": "SUP_VDD", "VGND": "SUP_VSS"}
        for i, p in enumerate(sorted(ext.keys())):
            portmap[p] = f"CTL_{i}_{re.sub(r'[^A-Za-z0-9]', '_', p)}"
        lines = [f".subckt RO_{canary.upper()} "
                 + " ".join(portmap[p] for p in ports)]
        for cell in ring:
            nodes, ctype = elements[cell]
            conns = [escape(portmap.get(n, portmap.get(n, n)))
                     if n not in dropped else "SUP_VSS" for n in nodes]
            lines.append(escape(cell) + " " + " ".join(conns) + f" {ctype}")
        lines.append(f".ends RO_{canary.upper()}")
        with open(os.path.join(outdir, f"{canary}_sel{can_sel}_loop.sp"),
                  "w") as fh:
            fh.write("\n".join(lines) + "\n")
        report["canaries"][f"{canary}_sel{can_sel}"]["portmap"] = portmap
    with open(os.path.join(outdir, "ro_loop.json"), "w") as fh:
        json.dump(report, fh, indent=1)
    print("\nwrote ro_loop.json")


if __name__ == "__main__":
    main()
