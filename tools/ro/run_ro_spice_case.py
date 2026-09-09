#!/usr/bin/env python3
"""Run the extracted-netlist transient SPICE check of one RO canary loop.

Deck structure (one case = one corner x one canary x one can_sel):

  .lib <PDK corner models>       mos_tt | mos_ss | mos_ff
  .include <PDK stdcell spice>   transistor-level cell models
  .include <ro_*_loop.sp>        ring subtree extracted from the post-route
                                 extracted netlist (see extract_ro.py)
  X1 <ports> RO_RO_GEN / RO_RO_MAT
  ... voltage sources for supplies and the ring control pins ...
  .control / tran / write raw / quit / .endc

The ring runs free once `en` is high; the loop control pins are the static
state the design holds during a canary window (en=1, mask=0, rst_n=1,
mux sel = can_sel).  The measurement itself is done by analyse_raw.py, which
finds threshold crossings in the saved waveform.

Usage: run_case.py --canary ro_gen --can-sel 0 --corner nom_typ_1p20V_25C
                   --outdir <dir> [--tstop-ns 4000] [--tstep-ps 1]
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# Every path is overridable so the same driver runs inside the devcontainer
# (ngspice/OpenVAF/PDK pre-installed) and on a host with a locally extracted
# ngspice.  In the devcontainer the defaults below resolve once
# .devcontainer/compile_pdk_osdi.sh has run and the PDK is present.
DEV = "/ttsetup/spice"
PDK = os.environ.get("SPICE_PDK_DIR", os.path.join(DEV, "pdk"))
LOOPS = os.environ.get("SPICE_LOOP_DIR", os.path.join(DEV, "ro_loop"))
NGSPICE = os.environ.get("SPICE_NGSPICE", "/usr/local/bin/ngspice")
NGSPICE_LIB = os.environ.get("SPICE_NGSPICE_LIB", "/usr/local/lib/ngspice")
NGSPICE_SCRIPTS = os.environ.get("SPICE_NGSPICE_SCRIPTS",
                                 "/usr/local/share/ngspice")

CORNERS = {
    "nom_fast_1p32V_m40C":  dict(lib="mos_ff", vdd=1.32, temp=-40),
    "nom_typ_1p20V_25C":    dict(lib="mos_tt", vdd=1.20, temp=25),
    "nom_slow_1p08V_125C":  dict(lib="mos_ss", vdd=1.08, temp=125),
}

# Ring control pins and the value each is held at during a canary window.
# Two naming styles are supported: the extracted netlist's own net names
# (extract_ro.py) and the self-describing port names from build_ring.py.
def control_role(orig):
    if orig == "VPWR":
        return "vdd"
    if orig == "VGND":
        return "vss"
    up = orig.upper()
    if "_EN" in up or "_0913_" in up:
        return "en"
    if "_MASK" in up or "_1330_" in up:
        return "mask"
    if "_RST_N" in up or "_FLOP_RST" in up or "FANOUT66" in up:
        return "rst_n"
    if "_SEL0" in up or "_1326_" in up:
        return "sel0"
    if "_SEL1" in up or "_1327_" in up:
        return "sel1"
    return "tie0"


def loop_node_name(canary, portmap, loop_sp):
    """Name of the gate output node inside the ring subcircuit.

    build_ring.py emits the RTL net name `N_NAND`; extract_ro.py keeps the
    extracted netlist's own name (the net driven by the gate's a3 cell).
    """
    body = open(loop_sp).read()
    # extract_ro.py keeps the extracted netlist's name for the gate output.
    cand = {"ro_gen": "_1351_/CLK", "ro_mat": "_1367_/CLK"}[canary]
    esc_cand = "".join(("\\" + ch) if ch in "[]()/.:$#@!%^&*+-=~`|<>?',;\""
                       else ch for ch in cand)
    if cand in body or esc_cand in body:
        return cand
    # build_ring.py uses the RTL net name.
    return "N_NAND"


def make_deck(canary, can_sel, corner, tstop_ns, tstep_ps, loop_sp, rawfile,
              solver=None, portmap=None):
    rawfile = os.path.abspath(rawfile)
    loop_sp = os.path.abspath(loop_sp)
    c = CORNERS[corner]
    sub = "RO_" + canary.upper()
    vals = {"en": 1, "mask": 0, "tie0": 0, "rst_n": 1,
            "sel0": can_sel & 1, "sel1": (can_sel >> 1) & 1}
    L = []
    L.append(f"* extracted RO transient: {canary} can_sel={can_sel} {corner}")
    L.append(f".lib '{PDK}/ngspice-models/cornerMOSlv.lib' {c['lib']}")
    L.append(f".lib '{PDK}/ngspice-models/cornerCAP.lib' cap_typ")
    L.append(f".lib '{PDK}/ngspice-models/cornerRES.lib' res_typ")
    L.append(f".lib '{PDK}/ngspice-models/cornerDIO.lib' dio_tt")
    L.append(f".include '{PDK}/sg13g2_stdcell.spice'")
    L.append(f".include '{loop_sp}'")
    L.append(f".temp {c['temp']}")
    conns = []
    for orig, port in sorted(portmap.items()):
        role = control_role(orig)
        if role == "vdd":
            L.append(f"Vpwr {port} 0 DC {c['vdd']}")
        elif role == "vss":
            L.append(f"Vgnd {port} 0 DC 0")
        else:
            v = vals.get(role, 0)
            L.append(f"V_{role}_{port} {port} DC {c['vdd'] if v else 0}")
        conns.append(port)
    L.append(f"X1 {' '.join(conns)} {sub}")
    # Initialise every ring node so the operating point is well defined and
    # the loop starts switching immediately (UIC skips the DC solve, which a
    # free-running ring does not need).
    nodes = ring_nodes(loop_sp)
    if nodes:
        L.append(".ic " + " ".join(f"v(x1.{n})=0" for n in nodes))
    # .save must appear in the deck (not the control block) to restrict what
    # the transient analysis stores: the rawfile would otherwise carry every
    # OSDI internal node (hundreds of vectors, ~250 MB per case).
    node = loop_node_name(canary, portmap, loop_sp)
    node_esc = "".join(("\\" + ch) if ch in "[]()/.:$#@!%^&*+-=~`|<>?',;\""
                        else ch for ch in node)
    saved = [f"v(x1.{node_esc})"] + [f"v({p})" for p in portmap.values()]
    L.append(".save " + " ".join(saved))
    L.append(".control")
    if solver:
        L.append(f"option {solver}")
    L.append(f"tran {tstep_ps}p {tstop_ns}n uic")
    # Save only the loop node and the control ports: the rawfile would
    # otherwise carry every OSDI internal node (hundreds of vectors, ~250 MB).
    L.append(f"write {rawfile}")
    L.append("quit")
    L.append(".endc")
    L.append(".end")
    return "\n".join(L) + "\n"


def run(canary, can_sel, corner, outdir, tstop_ns=4000.0, tstep_ps=1.0,
        solver=None, threads=None):
    os.makedirs(outdir, exist_ok=True)
    # Each can_sel has its own ring netlist: the tap mux is a selector, so
    # only one branch is part of the physical loop for a given setting.
    loop_sp = os.path.join(LOOPS, f"{canary}_sel{can_sel}_loop.sp")
    if not os.path.exists(loop_sp):
        raise SystemExit(f"missing {loop_sp}; run extract_ro.py first")
    # Portmap: {original netlist net: subcircuit port}.  extract_ro.py writes
    # it to ro_loop.json; build_ring.py uses self-describing port names.
    portmap = None
    meta = os.path.join(LOOPS, "ro_loop.json")
    if os.path.exists(meta):
        with open(meta) as fh:
            canaries = json.load(fh)["canaries"]
        key = f"{canary}_sel{can_sel}"
        if key in canaries and "portmap" in canaries[key]:
            portmap = canaries[key]["portmap"]
    if portmap is None:
        with open(loop_sp) as fh:
            header = fh.readline().split()
        portmap = {p: p for p in header[2:]}
    tag = f"{corner}_{canary}_sel{can_sel}"
    deck = os.path.join(outdir, f"{tag}.sp")
    raw = os.path.join(outdir, f"{tag}.raw")
    log = os.path.join(outdir, f"{tag}.log")
    with open(deck, "w") as fh:
        fh.write(make_deck(canary, can_sel, corner, tstop_ns, tstep_ps,
                           loop_sp, raw, solver, portmap))
    # ngspice reads .spiceinit from its CWD, so drop one next to the run.
    with open(os.path.join(outdir, ".spiceinit"), "w") as fh:
        fh.write("osdi '%s/osdi/psp103.osdi'\n" % PDK)
        fh.write("osdi '%s/osdi/psp103_nqs.osdi'\n" % PDK)
    env = dict(os.environ)
    env["PDK_ROOT"] = PDK
    env["PDK"] = "ihp-sg13g2"
    env["LD_LIBRARY_PATH"] = NGSPICE_LIB + ":" + env.get("LD_LIBRARY_PATH", "")
    env["SPICE_LIB_DIR"] = NGSPICE_SCRIPTS
    if threads:
        env["OMP_NUM_THREADS"] = str(threads)
    t0 = time.time()
    with open(log, "w") as lf:
        proc = subprocess.run([NGSPICE, "-b", os.path.abspath(deck)], stdout=lf,
                              stderr=subprocess.STDOUT, env=env, cwd=outdir)
    wall = time.time() - t0
    node = loop_node_name(canary, portmap, loop_sp)
    esc = "".join(("\\" + ch) if ch in "[]()/.:$#@!%^&*+-=~`|<>?',;\"" else ch
                  for ch in node)
    return dict(tag=tag, deck=deck, raw=raw, log=log, rc=proc.returncode,
                loop_node_raw=f"v(x1.{esc})",
                wall_s=round(wall, 2), tstop_ns=tstop_ns, tstep_ps=tstep_ps,
                corner=corner, canary=canary, can_sel=can_sel,
                vdd=CORNERS[corner]["vdd"], temp=CORNERS[corner]["temp"],
                lib=CORNERS[corner]["lib"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--canary", required=True, choices=["ro_gen", "ro_mat"])
    ap.add_argument("--can-sel", type=int, required=True, choices=[0, 1, 2, 3])
    ap.add_argument("--corner", required=True, choices=list(CORNERS))
    ap.add_argument("--outdir", default=os.path.join(HERE, "cases"))
    ap.add_argument("--tstop-ns", type=float, default=4000.0)
    ap.add_argument("--tstep-ps", type=float, default=1.0)
    ap.add_argument("--solver", default=None, choices=[None, "klu", "sparse"])
    ap.add_argument("--threads", type=int, default=None)
    a = ap.parse_args()
    info = run(a.canary, a.can_sel, a.corner, a.outdir,
               a.tstop_ns, a.tstep_ps, a.solver, a.threads)
    print(json.dumps(info, indent=1))


def escape_node(net):
    """Escape a net name the way the extracted netlist does."""
    out = []
    for ch in net:
        if ch in "[]()/.:$#@!%^&*+-=~`|<>?',;\"":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def ring_nodes(loop_sp):
    """Nets local to the ring subcircuit (excludes ports and supplies)."""
    ports = set()
    nodes = set()
    with open(loop_sp) as fh:
        for line in fh:
            if line.lower().startswith(".subckt"):
                ports.update(line.split()[2:])
            elif line.startswith("X") or line.startswith("x"):
                for n in line.split()[1:-1]:
                    nodes.add(n)
    return sorted(n for n in nodes if n not in ports)


if __name__ == "__main__":
    main()
