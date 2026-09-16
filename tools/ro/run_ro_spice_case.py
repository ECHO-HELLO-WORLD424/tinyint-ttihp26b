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


def _first_existing(*cands):
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def resolve_pdk_paths(pdk=None):
    """Resolve the model, stdcell and OSDI paths for the deck's `.lib` lines.

    `SPICE_PDK_DIR` may point either at a directory laid out for this tool
    (`<dir>/ngspice-models/...`, `<dir>/sg13g2_stdcell.spice`, `<dir>/osdi/...`)
    or directly at an installed PDK tree (`<dir>/libs.tech/ngspice/models/...`),
    which is what CIEL produces.  Both are accepted so the same drivers work
    against a hand-built tree and the devcontainer PDK.
    """
    import glob
    p = pdk or PDK
    models = _first_existing(os.path.join(p, "ngspice-models"),
                             os.path.join(p, "libs.tech", "ngspice", "models"))
    stdcell = _first_existing(os.path.join(p, "sg13g2_stdcell.spice"),
                              *glob.glob(os.path.join(
                                  p, "libs.ref", "**",
                                  "sg13g2_stdcell.spice"), recursive=True),
                              *glob.glob(os.path.join(
                                  p, "**", "sg13g2_stdcell.spice"),
                                  recursive=True))
    osdi = _first_existing(os.path.join(p, "osdi"),
                           os.path.join(p, "libs.tech", "ngspice", "osdi"))
    return dict(models=models, stdcell=stdcell, osdi=osdi)


PDK_PATHS = resolve_pdk_paths()


def pdk_include(name, family):
    """A `.lib` line for one corner file, resolved against the PDK layout."""
    if not PDK_PATHS["models"]:
        raise SystemExit(f"no ngspice models under {PDK}; set SPICE_PDK_DIR")
    return f".lib '{os.path.join(PDK_PATHS['models'], name)}' {family}"


def stdcell_include():
    if not PDK_PATHS["stdcell"]:
        raise SystemExit(f"no sg13g2_stdcell.spice under {PDK}")
    return f".include '{PDK_PATHS['stdcell']}'"


def spiceinit_lines():
    if not PDK_PATHS["osdi"]:
        raise SystemExit(f"no compiled OSDI models under {PDK}; run "
                         f".devcontainer/compile_pdk_osdi.sh")
    return ["osdi '%s/psp103.osdi'\n" % PDK_PATHS["osdi"],
            "osdi '%s/psp103_nqs.osdi'\n" % PDK_PATHS["osdi"]]


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


def loop_node_name(canary, portmap, loop_sp, loop_node=None):
    """Name of the gate output node inside the ring subcircuit.

    The loop node is the net driven by the RO gate's output cell.  Its flat net
    name is synthesis-assigned and changes between builds (`_1351_/CLK` in CI
    run 34158224984, `_1347_/CLK` in run 35034979531), so it is taken from the
    extraction metadata.  Guessing it from a fixed name silently saves a
    non-existent node: the deck runs, the rawfile contains no loop waveform, and
    the analysis reports "no oscillating node".
    """
    if loop_node:
        return loop_node
    cand = {"ro_gen": "_1351_/CLK", "ro_mat": "_1367_/CLK"}[canary]
    if cand in open(loop_sp).read():
        return cand
    return "N_NAND"


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


def make_deck(canary, can_sel, corner, tstop_ns, tstep_ps, loop_sp, rawfile,
              solver=None, portmap=None, control_roles=None, loop_node=None):
    rawfile = os.path.abspath(rawfile)
    loop_sp = os.path.abspath(loop_sp)
    c = CORNERS[corner]
    sub = "RO_" + canary.upper()
    vals = {"en": 1, "mask": 0, "tie0": 0, "rst_n": 1,
            "sel0": can_sel & 1, "sel1": (can_sel >> 1) & 1}
    L = []
    L.append(f"* extracted RO transient: {canary} can_sel={can_sel} {corner}")
    L.append(pdk_include("cornerMOSlv.lib", c["lib"]))
    L.append(pdk_include("cornerCAP.lib", "cap_typ"))
    L.append(pdk_include("cornerRES.lib", "res_typ"))
    L.append(pdk_include("cornerDIO.lib", "dio_tt"))
    L.append(stdcell_include())
    L.append(f".include '{loop_sp}'")
    L.append(f".temp {c['temp']}")
    conns = []
    roles = control_roles or {}
    port_to_orig = {port: orig for orig, port in portmap.items()}
    # The X-instance must follow the .subckt declaration order exactly.
    for port in subckt_ports(loop_sp, sub):
        orig = port_to_orig.get(port, port)
        # Structural roles from the extraction are preferred: net names in the
        # flat netlist are synthesis-assigned and change between builds, and
        # mis-tying the enable (or a tap select) changes what is measured.
        role = roles.get(orig) or control_role(orig)
        if role == "vdd":
            L.append(f"Vpwr {port} 0 DC {c['vdd']}")
        elif role == "vss":
            L.append(f"Vgnd {port} 0 DC 0")
        else:
            v = vals.get(role, 0)
            # NOTE: the ground node is mandatory.  "Vname node DC value"
            # silently leaves the node floating in ngspice (the parser takes
            # DC as the negative terminal), which is how an earlier version of
            # this driver produced uncontrolled control pins.
            L.append(f"V_{role}_{port} {port} 0 DC {c['vdd'] if v else 0}")
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
    node = loop_node_name(canary, portmap, loop_sp, loop_node)
    node_esc = "".join(("\\" + ch) if ch in "[]()/.:$#@!%^&*+-=~`|<>?',;\""
                        else ch for ch in node)
    # Save the loop node explicitly by its subcircuit-internal name, and again
    # through a named sense branch: some ngspice runs silently drop the
    # hierarchical vector (the rawfile then has no loop waveform at all), and
    # the zero-volt sense source gives the analysis a robust second name for the
    # same node.
    L.append(f"Vsense_{sub} {sub}_LOOP_SENSE 0 DC 0")
    L.append(f"Rloop_{sub} {sub}_LOOP_SENSE x1.{node_esc} 1G")
    saved = ([f"v(x1.{node_esc})", f"v({sub}_LOOP_SENSE)"]
             + [f"v({p})" for p in portmap.values()])
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
        solver=None, threads=None, loop_node=None):
    os.makedirs(outdir, exist_ok=True)
    # Each can_sel has its own ring netlist: the tap mux is a selector, so
    # only one branch is part of the physical loop for a given setting.
    loop_sp = os.path.join(LOOPS, f"{canary}_sel{can_sel}_loop.sp")
    if not os.path.exists(loop_sp):
        raise SystemExit(f"missing {loop_sp}; run extract_ro.py first")
    # Portmap: {original netlist net: subcircuit port}.  extract_ro.py writes
    # it to ro_loop.json; build_ring.py uses self-describing port names.
    portmap = None
    control_roles = {}
    meta = os.path.join(LOOPS, "ro_loop.json")
    if os.path.exists(meta):
        with open(meta) as fh:
            canaries = json.load(fh)["canaries"]
        key = f"{canary}_sel{can_sel}"
        if key in canaries and "portmap" in canaries[key]:
            portmap = canaries[key]["portmap"]
            control_roles = canaries[key].get("control_roles") or {}
            if loop_node is None:
                loop_node = canaries[key].get("loop_node")
    if portmap is None:
        with open(loop_sp) as fh:
            header = fh.readline().split()
        portmap = {p: p for p in header[2:]}
    loop_node = loop_node_name(canary, portmap, loop_sp, loop_node)
    tag = f"{corner}_{canary}_sel{can_sel}"
    deck = os.path.join(outdir, f"{tag}.sp")
    raw = os.path.join(outdir, f"{tag}.raw")
    log = os.path.join(outdir, f"{tag}.log")
    with open(deck, "w") as fh:
        fh.write(make_deck(canary, can_sel, corner, tstop_ns, tstep_ps,
                           loop_sp, raw, solver, portmap, control_roles,
                           loop_node))
    # ngspice reads .spiceinit from its CWD, so drop one next to the run.
    with open(os.path.join(outdir, ".spiceinit"), "w") as fh:
        fh.writelines(spiceinit_lines())
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
    esc = escape_node(loop_node)
    return dict(tag=tag, deck=deck, raw=raw, log=log, rc=proc.returncode,
                loop_node_raw=f"v(x1.{esc})",
                wall_s=round(wall, 2), tstop_ns=tstop_ns, tstep_ps=tstep_ps,
                corner=corner, canary=canary, can_sel=can_sel,
                vdd=CORNERS[corner]["vdd"], temp=CORNERS[corner]["temp"],
                lib=CORNERS[corner]["lib"],
                control_roles={k: v for k, v in sorted(control_roles.items())})


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
