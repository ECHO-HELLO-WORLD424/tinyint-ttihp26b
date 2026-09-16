#!/usr/bin/env python3
"""Run the counter-inclusive extracted-netlist transient test of one RO canary.

This is the companion of `run_ro_spice_case.py`.  That driver simulates the ring
subtree only, with the ripple counter's first flop present as a load but its D
and reset pins held at static values -- so the counter is held in reset and the
deck can only demonstrate oscillation.  This driver uses the `--counter`
extraction, in which the counter's toggle inverters and all 16 ripple stages are
inside the subcircuit, releases the reset, and then answers the question the
frequency dataset cannot:

    does the on-chip edge counter actually count the ring's edges at speed?

Deck differences from `run_ro_spice_case.make_deck`:

  * every counter bit's Q net is saved, so the final count and every bit
    transition are observable;
  * the shared reset tree is held **released** (VDD) after a short initial
    assertion (PWL 0 -> VDD), so the counter starts from a defined 0 and then
    runs;
  * `D` pins are no longer driven: inside the counter-inclusive subcircuit each
    stage's D is driven by its own toggle inverter (Q -> D), while the flop's
    clock is the ring node.  Nothing about the counter is pinned except the
    reset, which is released.

Usage:
  run_ro_count_case.py --loopdir <dir from extract_ro_loop.py --counter>
                       --canary ro_gen --can-sel 0 --corner nom_typ_1p20V_25C
                       --outdir <dir> [--periods 64] [--tstep-ps 5]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_ro_spice_case as ring_case  # noqa: E402

CORNERS = ring_case.CORNERS


def subckt_ports(loop_sp, subckt=None):
    """Port names of the extracted subcircuit, in `.subckt` declaration order.

    The X-instance in the deck must list its nodes in exactly this order; any
    other order silently connects control pins and counter outputs to the wrong
    subcircuit ports (ngspice does not check names).
    """
    for line in open(loop_sp):
        toks = line.split()
        if toks and toks[0].lower() == ".subckt":
            if subckt is None or toks[1] == subckt:
                return toks[2:]
    raise SystemExit(f"no .subckt line in {loop_sp}")


# Optional extra diagnostic nets (probe-only; keys are extracted-netlist net
# names, values the port names they should be exposed as).
EXTRA_NETS = {}


def bit_ports(portmap):
    """{bit index: port name} for the counter stages exposed as Q<n>."""
    out = {}
    for orig, port in portmap.items():
        m = re.fullmatch(r"Q(\d+)", port)
        if m:
            out[int(m.group(1))] = port
    return out


def loop_port(portmap, canary, loop_sp, loop_node=None):
    """Port name carrying the ring's loop node.

    The loop node is the net driven by the RO gate's output cell; its flat net
    name is synthesis-assigned, so it is read from the extraction metadata
    (`ro_loop.json`) rather than guessed from a fixed name.
    """
    node = loop_node or ring_case.loop_node_name(canary, portmap, loop_sp)
    for orig, port in portmap.items():
        if orig == node:
            return port
    for orig, port in portmap.items():
        if orig.replace("\\", "") == node:
            return port
    return None


def reset_ports(loop_sp, entry):
    """Ports that carry a counter flip-flop's RESET_B pin.

    The reset tree is a global buffer network shared by unrelated registers, so
    its net names (`fanout50/X`, `fanout64/X`, ...) carry no role information
    and change between builds.  The role is therefore found structurally: for
    every cell instance in the extracted subcircuit, ask which of its pins are
    the Q/CLK/D/RESET_B pins of a sequential cell, and expose those nets as
    roles.  Nets that appear only as RESET_B are the reset ports.
    """
    import extract_ro_loop as ex
    pin_table = ex.load_pin_table(None)
    if not pin_table:
        return set()
    pm = entry["portmap"]
    roles = {}
    for line in open(loop_sp):
        toks = line.split()
        if not toks or not toks[0].startswith("X"):
            continue
        inst = ex.unescape(toks[0])
        nodes = [ex.unescape(t) for t in toks[1:-1]]
        celltype = toks[-1]
        if not ex.is_flop(celltype):
            continue
        idx = ex.flop_pins(nodes, celltype, pin_table)
        if not idx:
            continue
        for key, pin in idx.items():
            net = nodes[pin]
            roles.setdefault(net, set()).add(key)
    return {pm[net] for net, keys in roles.items()
            if "rst" in keys and net in pm}


def controlled_ports(loop_sp, entry):
    """All ports that carry a sequential cell's control pin, by role."""
    import extract_ro_loop as ex
    pin_table = ex.load_pin_table(None)
    pm = entry["portmap"]
    roles = {}
    if pin_table:
        for line in open(loop_sp):
            toks = line.split()
            if not toks or not toks[0].startswith("X"):
                continue
            nodes = [ex.unescape(t) for t in toks[1:-1]]
            celltype = toks[-1]
            if not ex.is_flop(celltype):
                continue
            idx = ex.flop_pins(nodes, celltype, pin_table)
            if not idx:
                continue
            for key, pin in idx.items():
                net = nodes[pin]
                roles.setdefault(net, set()).add(key)
    out = {}
    for net, keys in roles.items():
        if net in pm:
            out[pm[net]] = keys
    return out


def make_deck(canary, can_sel, corner, loop_sp, rawfile, portmap, loop_port_name,
              bitmaps, tstop_ns, tstep_ps, solver=None, reset_release_ns=2.0,
              reset_port_set=None, control_roles=None, extra_nets=None):
    rawfile = os.path.abspath(rawfile)
    loop_sp = os.path.abspath(loop_sp)
    c = CORNERS[corner]
    sub = "RO_" + canary.upper()
    # en=1 and mask=0 open the ring gate; sel picks the tap; the reset tree is
    # released after `reset_release_ns` so the counter starts from zero.
    vals = {"en": 1, "mask": 0, "tie0": 0, "rst_n": 1,
            "sel0": can_sel & 1, "sel1": (can_sel >> 1) & 1}
    reset_port_set = reset_port_set or set()
    port_to_orig = {port: orig for orig, port in portmap.items()}
    L = []
    L.append(f"* counter-inclusive extracted RO transient: {canary} "
             f"can_sel={can_sel} {corner} (reset released, counter running)")
    L.append(ring_case.pdk_include("cornerMOSlv.lib", c["lib"]))
    L.append(ring_case.pdk_include("cornerCAP.lib", "cap_typ"))
    L.append(ring_case.pdk_include("cornerRES.lib", "res_typ"))
    L.append(ring_case.pdk_include("cornerDIO.lib", "dio_tt"))
    L.append(ring_case.stdcell_include())
    L.append(f".include '{loop_sp}'")
    L.append(f".temp {c['temp']}")
    conns = []
    roles = control_roles or {}
    bit_ports_set = {f"Q{b}" for b in bitmaps}
    # The X-instance must follow the .subckt declaration order exactly.
    for port in subckt_ports(loop_sp, sub):
        orig = port_to_orig.get(port, port)
        if port in bit_ports_set:
            # Counter outputs are observations, not inputs: never drive them.
            conns.append(port)
            continue
        if orig in ("VPWR", "VGND"):
            role = "vdd" if orig == "VPWR" else "vss"
        elif orig in roles:
            # structural role from the extraction (build-independent)
            role = roles[orig]
        elif port in reset_port_set:
            role = "rst_n"
        else:
            # fallback for extractions without structural roles
            role = ring_case.control_role(orig)
        if role == "vdd":
            L.append(f"Vpwr {port} 0 DC {c['vdd']}")
        elif role == "vss":
            L.append(f"Vgnd {port} 0 DC 0")
        else:
            v = vals.get(role, 0)
            if role == "rst_n" and reset_release_ns > 0:
                # Hold the counter in reset for a defined startup, then release.
                L.append(f"V_{role}_{port} {port} 0 PWL(0 0 "
                         f"{reset_release_ns}n {c['vdd']})")
            else:
                L.append(f"V_{role}_{port} {port} 0 DC "
                         f"{c['vdd'] if v else 0}")
        conns.append(port)
    L.append(f"X1 {' '.join(conns)} {sub}")
    # Ring nodes all start low; with uic the ring switches immediately from the
    # unbalanced .ic.  Counter nodes are left at zero, which is the state the
    # released reset holds them in for the first `reset_release_ns`.
    nodes = ring_case.ring_nodes(loop_sp)
    if nodes:
        L.append(".ic " + " ".join(f"v(x1.{n})=0" for n in nodes))
    # Only the loop node, the counter bits and the control ports are saved; the
    # rawfile would otherwise carry every OSDI internal node.
    saved = [f"v(x1.{ring_case.escape_node(loop_port_name)})"] + \
            [f"v(x1.{bitmaps[b]})" for b in sorted(bitmaps)] + \
            [f"v(x1.{ring_case.escape_node(n)})" for n in extra_nets] + \
            [f"v({p})" for p in portmap.values()]
    L.append(".save " + " ".join(saved))
    L.append(".control")
    if solver:
        L.append(f"option {solver}")
    L.append(f"tran {tstep_ps}p {tstop_ns}n uic")
    L.append(f"write {rawfile}")
    L.append("quit")
    L.append(".endc")
    L.append(".end")
    return "\n".join(L) + "\n"


def planned_tstop_ns(period_s, periods, cap_ns, settle_ns=6.0):
    """Simulated time long enough for `periods` ring periods plus settling."""
    want = settle_ns + periods * period_s * 1e9 * 1.15
    return round(min(want, cap_ns), 2)


def load_loops(loopdir, canary, can_sel):
    loop_sp = os.path.join(loopdir, f"{canary}_sel{can_sel}_loop.sp")
    if not os.path.exists(loop_sp):
        raise SystemExit(f"missing {loop_sp}; run extract_ro_loop.py "
                         f"--counter first")
    meta = os.path.join(loopdir, "ro_loop.json")
    with open(meta) as fh:
        entry = json.load(fh)["canaries"][f"{canary}_sel{can_sel}"]
    return loop_sp, entry


def run(canary, can_sel, corner, loopdir, outdir, periods=64.0, tstep_ps=5.0,
        solver="klu", tstop_cap_ns=2000.0, reset_release_ns=2.0,
        period_hint_s=None):
    os.makedirs(outdir, exist_ok=True)
    loop_sp, entry = load_loops(loopdir, canary, can_sel)
    portmap = entry["portmap"]
    bitmaps = bit_ports(portmap)
    if not bitmaps:
        raise SystemExit(f"{loop_sp} has no Q<n> ports; regenerate the "
                         f"extraction with --counter")
    lp = loop_port(portmap, canary, loop_sp, entry.get("loop_node"))
    if lp is None:
        # Counter-inclusive extraction keeps the loop node internal: it is the
        # CLK pin of the counter's first stage, not a subcircuit port.
        lp = entry.get("loop_node")
        if lp is None:
            raise SystemExit(f"cannot identify the loop node in {loop_sp}")
    if period_hint_s is None:
        raise SystemExit("a period hint is required to size the transient run")
    tstop_ns = planned_tstop_ns(period_hint_s, periods, tstop_cap_ns,
                               settle_ns=reset_release_ns + 4.0)
    tag = f"{corner}_{canary}_sel{can_sel}"
    deck = os.path.join(outdir, f"{tag}.sp")
    raw = os.path.join(outdir, f"{tag}.raw")
    log = os.path.join(outdir, f"{tag}.log")
    roles = entry.get("control_roles") or {}
    extra_nets = list(EXTRA_NETS)
    rports = set() if roles else reset_ports(loop_sp, entry)
    croles = controlled_ports(loop_sp, entry)
    with open(deck, "w") as fh:
        fh.write(make_deck(canary, can_sel, corner, loop_sp, raw, portmap, lp,
                           bitmaps, tstop_ns, tstep_ps, solver,
                           reset_release_ns, rports, roles, extra_nets))
    with open(os.path.join(outdir, ".spiceinit"), "w") as fh:
        fh.writelines(ring_case.spiceinit_lines())
    env = dict(os.environ)
    env["PDK_ROOT"] = ring_case.PDK
    env["PDK"] = "ihp-sg13g2"
    env["LD_LIBRARY_PATH"] = ring_case.NGSPICE_LIB + ":" + \
        env.get("LD_LIBRARY_PATH", "")
    env["SPICE_LIB_DIR"] = ring_case.NGSPICE_SCRIPTS
    t0 = time.time()
    with open(log, "w") as lf:
        proc = subprocess.run([ring_case.NGSPICE, "-b", os.path.abspath(deck)],
                              stdout=lf, stderr=subprocess.STDOUT, env=env,
                              cwd=outdir)
    wall = time.time() - t0
    return dict(tag=tag, deck=deck, raw=raw, log=log, rc=proc.returncode,
                wall_s=round(wall, 2), tstop_ns=tstop_ns, tstep_ps=tstep_ps,
                corner=corner, canary=canary, can_sel=can_sel,
                vdd=CORNERS[corner]["vdd"], temp=CORNERS[corner]["temp"],
                lib=CORNERS[corner]["lib"], loop_port=lp,
                bit_ports={str(k): v for k, v in sorted(bitmaps.items())},
                n_bits=len(bitmaps), reset_release_ns=reset_release_ns,
                loop_sp=os.path.abspath(loop_sp),
                ring_cells=entry.get("n_ring_cells"),
                control_roles={k: v for k, v in sorted(roles.items())},
                extra_nets={k: v for k, v in sorted(EXTRA_NETS.items())},
                chain=[s.get("flop") for s in entry.get("counter_chain", [])])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--canary", required=True, choices=["ro_gen", "ro_mat"])
    ap.add_argument("--can-sel", type=int, required=True, choices=[0, 1, 2, 3])
    ap.add_argument("--corner", required=True, choices=list(CORNERS))
    ap.add_argument("--loopdir", required=True)
    ap.add_argument("--outdir", default=os.path.join(HERE, "count-cases"))
    ap.add_argument("--periods", type=float, default=64.0)
    ap.add_argument("--tstep-ps", type=float, default=5.0)
    ap.add_argument("--tstop-cap-ns", type=float, default=2000.0)
    ap.add_argument("--reset-release-ns", type=float, default=2.0)
    ap.add_argument("--period-s", type=float, default=None,
                    help="ring period in seconds (sizes the run); normally "
                         "taken from a measured oscillation result")
    ap.add_argument("--solver", default="klu", choices=[None, "klu", "sparse"])
    a = ap.parse_args()
    info = run(a.canary, a.can_sel, a.corner, a.loopdir, a.outdir,
               a.periods, a.tstep_ps, a.solver, a.tstop_cap_ns,
               a.reset_release_ns, a.period_s)
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
