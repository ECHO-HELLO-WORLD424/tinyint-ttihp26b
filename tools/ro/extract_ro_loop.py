#!/usr/bin/env python3
"""Extract one RO canary loop from the flat, extracted top-level SPICE netlist.

The extracted netlist (Magic spiceextraction) is flat: every standard cell is
an X-instance at the top level with escaped net names, so both ring oscillators
are directly visible as cycles over those nets.  Simulating the whole 1x1 chip
(about 1,600 non-filler instances, transistor level) is unnecessary for an f_osc
measurement; the ring plus its enable gate and the first counter flop is enough.

The loop is traced explicitly: start at the NAND-gate output (the `nand_out` /
`ro_node` net), then repeatedly follow the single cell that drives the current
net until the traversal returns to the start.  Every cell on that path is a
member of the ring.  Inputs of ring cells that are not driven by another ring
cell are the ring's external control pins: en, mask and the mux `sel` bits.
Those are turned into subcircuit ports so a deck can drive them exactly.

The optional `--counter` mode additionally pulls the canary's *ripple edge
counter* into the subcircuit, so a deck can exercise the counter's toggle
feedback instead of holding it in reset:

  * the first counter flop is the cell clocked directly by the loop node;
  * each stage k is a flop whose Q drives an inverter back into its own D (the
    toggle) and another inverter that clocks stage k+1 (the ripple);
  * the walk stops at `--chain-depth` stages or when no further stage is found.

Without this mode the counter flop is present only as a capacitive load on the
loop node, its D and reset pins are treated as external control pins, and any
deck built from the result necessarily holds the counter static (the pin values
the old decks used are 0 V on D and on the shared reset tree, i.e. the counter
is held in reset).  That is enough to measure f_osc, but it cannot show that the
counter counts.

Usage:  extract_ro.py <netlist> <outdir> [--counter] [--chain-depth N]

`--include-q0` is implied by `--counter`: the loop-node flop's Q net becomes a
port named `Q0` so a deck can save (and therefore observe) the counter's LSB.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

ESCAPE = re.compile(r"\\(.)")
SPECIAL = set("[]()/.:$#@!%^&*+-=~`|<>?',;\"")

# Sequential cells whose Q output is the counter bit.  The ripple counter is
# built from reset-and-scan flops (`dfrbpq_1` in the current netlists).
FLOP_RE = re.compile(r"^sg13g2_(s?df[rx]bpq?|s?df[rx]tpq?)_\d+$")


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


def pin_index(nodes, suffix):
    """Index of the pin whose escaped name ends in `suffix` (e.g. '/CLK').

    Hierarchical instances name their pins after the cell's own instance, so a
    suffix is the only stable way to find one; flat top-level instances instead
    carry the PDK subcircuit's pin names, which `load_pin_table` maps.
    """
    for i, n in enumerate(nodes):
        if n.endswith(suffix):
            return i
    return None


def load_pin_table(path):
    """Map cell type -> pin names from the PDK stdcell SPICE models.

    The flat extracted netlist names X-instance pins by the PDK subcircuit's
    pin order but does not repeat the pin names, so positions must come from
    the models.  `path` may be given explicitly, or found via `SPICE_STDCELL`
    / `SPICE_PDK_DIR`.
    """
    import glob
    cands = []
    if path:
        cands.append(path)
    if os.environ.get("SPICE_STDCELL"):
        cands.append(os.environ["SPICE_STDCELL"])
    pdk = os.environ.get("SPICE_PDK_DIR")
    if pdk:
        cands += glob.glob(os.path.join(pdk, "..", "..", "libs.ref", "**",
                                        "sg13g2_stdcell.spice"),
                           recursive=True)
        cands += glob.glob(os.path.join(pdk, "**", "sg13g2_stdcell.spice"),
                           recursive=True)
    table = {}
    for c in cands:
        if not c or not os.path.exists(c):
            continue
        with open(c) as fh:
            for line in fh:
                low = line.lower()
                if low.startswith(".subckt"):
                    toks = line.split()
                    table[toks[1]] = toks[2:]
        if table:
            break
    return table


def is_flop(celltype):
    return bool(FLOP_RE.match(celltype))


def flop_pins(nodes, celltype, pin_table):
    """(Q, CLK, D, RESET_B) positional indices for a sequential cell."""
    names = pin_table.get(celltype) or []
    idx = {}
    for want, key in (("Q", "q"), ("CLK", "clk"), ("D", "d"),
                      ("RESET_B", "rst")):
        if want in names:
            idx[key] = names.index(want)
    if set(idx) == {"q", "clk", "d", "rst"}:
        return idx
    return {}


def trace_tap_selects(elements, canon, ring, loop_cell, max_cells=40):
    """Cells that are tap-mux controlled: their data inputs reach the loop.

    A cell's input is "data" when the net is driven by a ring cell (or is the
    loop net itself).  Walking that relation outwards from the RO gate collects
    the delay line, the tap mux and the adder cells; the external pins that
    remain on those cells are the select pins.
    """
    seen = {loop_cell}
    stack = [loop_cell]
    while stack and len(seen) < max_cells:
        c = stack.pop()
        for n in elements[c][0][1:]:
            if n in ("VPWR", "VGND"):
                continue
            drv = canon.get(n, ("ext", n))
            if drv[0] == "drv" and drv[1] in ring and drv[1] not in seen:
                seen.add(drv[1])
                stack.append(drv[1])
    return seen


def infer_control_roles(elements, drivers, loads, canon, ring, gate_out, canary):
    """Role of every external control net, from the subcircuit's structure.

    Net names in the flat extracted netlist are synthesis-assigned and change
    from build to build (`_0898_/Y` carries the RO enable in the current build
    but `_0913_/X` did in an earlier one), so the decks cannot identify a
    control pin by name.  The roles are instead derived from where the net sits:

      * `en`  - the input of the NAND/AND cell whose output is the loop node
                that is not the feedback input and not the reset input;
      * `mask`- the external input of the RO's own inverting cell in the gate
                tree (`u_im`), which the RTL drives from `mask`;
      * reset - an external net that also drives a flop's RESET_B pin (the
                shared reset tree) or the RO gate's reset input (`u_a2`);
      * `sel0`,`sel1` - the external pins on the cells that carry the tap mux,
                ordered by how many select pins they drive.
    """
    def ext_of(cell, members):
        """Pins of `cell` whose driver is outside the subcircuit `members`.

        A net is internal only when one of the cells being included drives it.
        Nets driven by cells outside the included set (including nets driven
        elsewhere in the design, such as the RO enable's buffer in the top
        level) are external control pins and must become ports.
        """
        out = []
        for n in elements[cell][0][1:]:
            if n in ("VPWR", "VGND"):
                continue
            drv = [d for d in drivers.get(canon.get(n, ("ext", n)), [])
                   if d in members]
            if not drv:
                out.append(n)
        return out

    loop_cell = [d for d in drivers.get(canon.get(gate_out), [])
                 if d.startswith(f"Xu_{canary}.")]
    loop_cell = loop_cell[0] if loop_cell else None
    roles = {}

    # reset tree: any external net reaching a sequential cell's RESET_B pin
    if loop_cell is not None:
        for c in trace_tap_selects(elements, canon, set(ring), loop_cell):
            ext = ext_of(c, set(ring) | {c})
            for n in ext:
                rst_users = [u for u in loads.get(canon.get(n, ("ext", n)), [])
                             if is_flop(elements[u][1])]
                if rst_users:
                    roles[n] = "rst_n"

    # the RO's own gate tree (u_gate) holds en, mask and the reset input
    gate_cells = [c for c in elements if f"u_{canary}.u_gate" in c]
    gate_members = set(gate_cells) | set(ring)
    gate_ext = []
    for c in sorted(gate_cells):
        gate_ext += ext_of(c, gate_members)
    # The RO's gate tree is `nand_out = en & ~(mask & rst_n)` (the RTL's
    # tpv_ro_gate).  The mask input arrives through the RO's own inverter
    # (`u_im`), so the external net that drives that inverter is `mask`; the
    # other external net reaching the gate tree is the enable.
    mask_nets = set()
    for c in [c for c in gate_cells if c.endswith("u_im")]:
        for n in ext_of(c, gate_members):
            mask_nets.add(n)
            roles[n] = "mask"
    for n in gate_ext:
        if n in mask_nets or n in roles:
            continue
        # a gate-tree net can also carry the shared reset tree into the gate
        if any(is_flop(elements[u][1])
               for u in loads.get(canon.get(n, ("ext", n)), [])):
            roles[n] = "rst_n"
            continue
        if "en" not in roles.values():
            roles[n] = "en"

    # tap mux selects: external pins on the cells that reach the loop node
    if loop_cell is not None:
        select_nets = []
        members = set(ring) | {loop_cell}
        for c in sorted(trace_tap_selects(elements, canon, set(ring),
                                          loop_cell)):
            if f"u_{canary}." not in c:
                continue
            nodes = elements[c][0]
            data_pins = set(nodes[1:3]) if "mux" in elements[c][1] else set()
            for n in ext_of(c, members):
                # A mux's A0/A1 inputs can be undriven stubs too; they are data
                # pins, not selects, so only the S pin (index 3) is a select.
                if n in data_pins or n in roles:
                    continue
                select_nets.append(n)
        counts = {}
        for n in select_nets:
            counts[n] = counts.get(n, 0) + len(
                loads.get(canon.get(n, ("ext", n)), []))
        for i, n in enumerate(sorted(counts, key=lambda x: (-counts[x], x))[:2]):
            roles[n] = f"sel{i}"
    return roles


def ripple_chain(elements, drivers, loads, canon, first_flop, max_depth,
                 pin_table):
    """Walk the ripple edge counter outwards from its first stage.

    Stage k is the flop clocked by the loop (k = 0) or by an inverter driven by
    stage k-1's Q.  Each stage's toggle is a cell in the flip-flop's own D cone
    whose input is the flop's Q; its ripple clock is the cell that drives the
    next stage's CLK pin from that same Q.

    Returns (stages, stop_reason).
    """
    stages = []
    flop = first_flop
    seen = set()
    reason = "no further stage found"
    while flop is not None and len(stages) < max_depth:
        if flop in seen:
            reason = "stage repeated (loop in the chain walk)"
            break
        seen.add(flop)
        nodes, ctype = elements[flop]
        idx = flop_pins(nodes, ctype, pin_table)
        if not idx:
            reason = f"{flop}: cannot locate Q/CLK/D/RESET_B pins"
            break
        q_net, d_net = nodes[idx["q"]], nodes[idx["d"]]
        # toggle: a cell that reads Q and drives the flop's D
        toggle = [c for c in loads.get(canon.get(q_net, ("ext", q_net)), [])
                  if c != flop and elements[c][0][0] == d_net]
        # ripple: a cell that reads Q and drives another flop's CLK pin
        nxt = None
        clk_drv = []
        for c in loads.get(canon.get(q_net, ("ext", q_net)), []):
            if c == flop or c in seen:
                continue
            out_net = elements[c][0][0]
            for cand, (cnodes, cct) in elements.items():
                if cand == flop or not is_flop(cct):
                    continue
                cidx = flop_pins(cnodes, cct, pin_table)
                if cidx and cnodes[cidx["clk"]] == out_net:
                    if nxt is None:
                        nxt = cand
                        clk_drv = [c]
                    elif cand != nxt:
                        reason = f"stage {len(stages)}: Q drives two flops"
        stages.append(dict(flop=flop, ctype=ctype, q_net=q_net, d_net=d_net,
                           rst_net=nodes[idx["rst"]], toggle=toggle,
                           clk_driver=clk_drv, next=nxt))
        if nxt is None:
            reason = "chain ended (last stage has no rippled successor)"
        flop = nxt
    else:
        if flop is not None:
            reason = f"stopped at --chain-depth {max_depth}"
    return stages, reason


def check_counter_extraction(elements, ring, chain, ctl_roles, pin_table):
    """Fail loudly if the extracted counter could not actually run.

    Three ways this mode can silently reproduce the defect it exists to fix:

      1. the chain walk stops short, so part of the counter is left outside;
      2. a flip-flop's D pin has no driver inside the subcircuit -- the deck
         then has to drive it, which pins the counter;
      3. the reset tree's input is not exposed as a `rst_n` port, so the deck
         cannot release it.

    Returns a list of problems (empty when the extraction is usable).
    """
    problems = []
    members = set(ring)
    for i, stage in enumerate(chain):
        nodes, ctype = elements[stage["flop"]]
        idx = flop_pins(nodes, ctype, pin_table)
        if not idx:
            problems.append(f"stage {i}: no Q/CLK/D/RESET_B pins")
            continue
        d_net = nodes[idx["d"]]
        drv = [d for d in drivers_of_net(elements, d_net) if d in members]
        if not drv:
            problems.append(
                f"stage {i} ({stage['flop']}): D pin {d_net!r} has no driver "
                f"inside the subcircuit -- the deck would pin the counter")
    if "rst_n" not in ctl_roles.values():
        problems.append("no control pin has the rst_n role -- the deck cannot "
                        "release the counter's reset")
    return problems


def drivers_of_net(elements, net):
    return [c for c, (nodes, _) in elements.items() if nodes and nodes[0] == net]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("netlist")
    ap.add_argument("outdir")
    ap.add_argument("--counter", action="store_true",
                    help="include the ripple edge counter and its toggle "
                         "feedback in the extracted subcircuit")
    ap.add_argument("--chain-depth", type=int, default=16,
                    help="number of ripple-counter stages to include "
                         "(default 16 = the full counter)")
    ap.add_argument("--loop-node", default=None,
                    help="override the loop-node net name (default: discovered "
                         "from the RO hierarchy's gate output)")
    ap.add_argument("--stdcell-spice", default=None,
                    help="sg13g2_stdcell.spice used for cell pin order "
                         "(default: $SPICE_STDCELL, else under $SPICE_PDK_DIR)")
    args = ap.parse_args()
    netlist, outdir = args.netlist, args.outdir
    os.makedirs(outdir, exist_ok=True)
    subckts, toplevel, top_name = parse_netlist(netlist)
    if top_name in subckts and subckts[top_name]["lines"]:
        toplevel = toplevel + subckts[top_name]["lines"]
    elements, drivers, loads, canon = build_graph(toplevel)
    pin_table = load_pin_table(args.stdcell_spice)
    if args.counter and not pin_table:
        raise SystemExit("--counter needs the PDK stdcell SPICE models for "
                         "cell pin order; pass --stdcell-spice or set "
                         "SPICE_STDCELL / SPICE_PDK_DIR")

    # The flat net names are synthesis-assigned and change between builds, so
    # locate each canary's loop node from the RO hierarchy itself (the gate's
    # output) unless one is given explicitly.
    def discover_loop_node(canary):
        outs = []
        for inst, (nodes, ctype) in elements.items():
            if inst.endswith("u_gate.u_a3") and f"u_{canary}." in inst:
                outs.append(nodes[0])
        if len(outs) != 1:
            raise RuntimeError(f"{canary}: expected 1 gate output, got {outs}")
        return outs[0]

    report = {"netlist": os.path.basename(netlist), "top_subckt": top_name,
              "instances_total": len(elements),
              "counter_included": bool(args.counter),
              "chain_depth": args.chain_depth if args.counter else 0,
              "pin_table_cells": len(pin_table),
              "canaries": {}}
    for canary in ("ro_gen", "ro_mat"):
      gate_out = args.loop_node or discover_loop_node(canary)
      for can_sel in range(4):
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
        members = set()
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
        # Optional counter expansion: pull in the ripple edge counter so a deck
        # can exercise the toggle feedback.  Without it the counter's own logic
        # stays outside the subcircuit and its D / reset pins are ports, which
        # pins the counter (the ring-only decks hold it in reset).
        chain = []
        if args.counter:
            flops_on_loop = [l for l in loads_ring if is_flop(elements[l][1])]
            if len(flops_on_loop) != 1:
                raise RuntimeError(f"{canary}: expected 1 counter flop on the "
                                   f"loop node, got {flops_on_loop}")
            chain, reason = ripple_chain(elements, drivers, loads, canon,
                                         flops_on_loop[0], args.chain_depth,
                                         pin_table)
            print(f"  counter chain: {len(chain)} stage(s) included "
                  f"({reason})")
            # The chain is complete only when it ends because the last stage
            # has no rippled successor; if it stopped at a depth limit or hit a
            # repeated stage, part of the counter is missing and the extraction
            # cannot show that the counter counts.
            if reason != "chain ended (last stage has no rippled successor)":
                raise SystemExit(
                    f"{canary} sel{can_sel}: counter chain extraction stopped "
                    f"early: {reason} ({len(chain)} stage(s) found); a partial "
                    f"chain cannot show that the counter counts")
            for stage in chain:
                for c in [stage["flop"]] + stage["toggle"] + stage["clk_driver"]:
                    if c not in ring:
                        ring.append(c)
                        print(f"    + counter cell {c} ({elements[c][1]})")
            ring = sorted(ring)
        if args.counter:
            # A real canary window holds `rst_n` released, so the flops need
            # their actual reset source.  The shared reset tree is built from
            # generic buffer cells (`fanout50/X` ... `fanout66/X`) that sit
            # outside the RO hierarchy and carry no role information in the
            # netlist, so walk each flip-flop control pin's driver chain until
            # it reaches an independent net (no driver, or several) and include
            # every cell on the way.  Otherwise the tree's internal nets become
            # ports; the deck then drives one buffer output against another and
            # the downstream flops stay in reset, which is exactly the state
            # this mode exists to avoid.
            def drv_cells(net):
                """Cells of the netlist that drive `net`, matching by node name.

                The flat extracted netlist names a net after the output pin of
                the cell that drives it, but a buffer's *input* pin can carry
                the same name as another buffer's output (`Xfanout66` lists
                `fanout67/X` as its input while `fanout67/X` is also named as
                the output of `Xfanout67`).  Driver lookup is therefore
                positional (pin 0 of the instance), not name-based.
                """
                out = []
                for c, (nodes, ctype) in elements.items():
                    if nodes and nodes[0] == net:
                        out.append(c)
                return out

            def walk_up(net):
                """Include the single-driver chain that produces `net`."""
                step = 0
                while step < 32:
                    step += 1
                    drvs = drv_cells(net)
                    if len(drvs) != 1:
                        return          # no driver, or several: independent net
                    d = drvs[0]
                    if d in members:
                        return
                    members.add(d)
                    if d not in ring:
                        ring.append(d)
                    nodes, ctype = elements[d]
                    ins = [n for n in nodes[1:] if n not in ("VPWR", "VGND")]
                    if len(ins) != 1:
                        return      # multi-input cell: its other inputs are ports
                    net = ins[0]

            frontier = [c for c in ring if is_flop(elements[c][1])]
            while frontier:
                c = frontier.pop()
                nodes, ctype = elements[c]
                idx = flop_pins(nodes, ctype, pin_table) if is_flop(ctype) else {}
                for key in ("rst", "clk"):
                    if key in idx:
                        walk_up(nodes[idx[key]])
            ring = sorted(set(ring))
        # After the counter expansion the reset tree's own buffer cells are
        # inside the subcircuit, so their outputs (`fanout50/X`, ...) are
        # internal and must NOT become ports: driving them from the deck both
        # fights the buffer and leaves the downstream flops held in reset.
        members |= set(ring)
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
                       if d in members]
                if not drv:
                    ext.setdefault(pin, []).append(cell)
        print(f"\n{canary} sel{can_sel}: ring cells={len(ring)}")
        print(f"  loop node: {gate_out}")
        print(f"  external control pins ({len(ext)}):")
        for pin, users in sorted(ext.items()):
            print(f"    {pin:45s} -> {', '.join(users)}")
        ctl_roles = infer_control_roles(elements, drivers, loads, canon, ring,
                                        gate_out, canary)
        for net in ext:
            # The reset tree's root input keeps the chip-level port name (the
            # synthesiser does not rename a top-level input), which identifies
            # it directly; the buffer-chain walk above makes it the only reset
            # port.
            if net.endswith("rst_n") and "rst_n" not in ctl_roles.values():
                ctl_roles[net] = "rst_n"
        print(f"  non-ring loads on loop node: {loads_ring}")
        print("  inferred control roles:")
        for net, role in sorted(ctl_roles.items(), key=lambda kv: kv[1]):
            print(f"    {role:6s} <- {net}")
        report["canaries"][f"{canary}_sel{can_sel}"] = {
            "canary": canary,
            "can_sel": can_sel,
            "loop_node": gate_out,
            "ring_cells": ring,
            "n_ring_cells": len(ring),
            "external_pins": {k: v for k, v in sorted(ext.items())},
            "control_roles": {k: v for k, v in sorted(ctl_roles.items())},
            "loop_node_loads": loads_ring,
        }
        # Counter expansion also exposes each stage's Q net as an output port so
        # a deck can save the counter state and compare it with the edge count.
        bit_ports = {}
        if chain:
            for i, stage in enumerate(chain):
                bit_ports[f"Q{i}"] = stage["q_net"]
            report["canaries"][f"{canary}_sel{can_sel}"]["counter_chain"] = [
                {"bit": i, "flop": s["flop"], "ctype": s["ctype"],
                 "q_net": s["q_net"], "d_net": s["d_net"],
                 "rst_net": s["rst_net"], "toggle": s["toggle"],
                 "clk_driver": s["clk_driver"], "next": s["next"]}
                for i, s in enumerate(chain)]
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
        # Rename every node that the subcircuit sees from outside so it cannot
        # collide with the flat top-level net names of the extracted netlist
        # (a subcircuit port and a top-level net with the same name are two
        # different nodes; supplies would silently float, and control pins
        # would never be driven).
        portmap = {"VPWR": "SUP_VDD", "VGND": "SUP_VSS"}
        ports = ["SUP_VDD", "SUP_VSS"]
        for i, p in enumerate(sorted(ext.keys())):
            name = f"CTL_{i}_{re.sub(r'[^A-Za-z0-9]', '_', p)}"
            portmap[p] = name
            ports.append(name)
        # Counter bit outputs last, so the CTL_* indices of the control pins do
        # not depend on whether the counter was included.
        for name in sorted(bit_ports):
            portmap[bit_ports[name]] = name
            ports.append(name)
        lines = [f".subckt RO_{canary.upper()} " + " ".join(ports)]
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
        if args.counter:
            problems = check_counter_extraction(elements, ring, chain,
                                                ctl_roles, pin_table)
            report["canaries"][f"{canary}_sel{can_sel}"]["self_check"] = (
                "ok" if not problems else "; ".join(problems))
            if problems:
                raise SystemExit(f"{canary} sel{can_sel}: " +
                                 "; ".join(problems))
    with open(os.path.join(outdir, "ro_loop.json"), "w") as fh:
        json.dump(report, fh, indent=1)
    print("\nwrote ro_loop.json")


if __name__ == "__main__":
    main()
