#!/usr/bin/env python3
"""Generation fixture for the wire-capacitance deck builder.

Gate 2 needs the wire-capacitance sensitivity run to be trustworthy.  The first
attempt was not: `add_wire_caps.py` converted the SPEF capacitance to pF but
wrote the number **without a SPICE scale suffix**, and an unsuffixed capacitor
value is in farads, so every injected capacitor was 10**12 times too large and
the loop stalled.  The stall was then recorded as a property of the modified
subcircuit ("structural, not a magnitude effect") instead of a unit bug in the
generator.

This fixture builds a two-inverter loop with two known SPEF nets (2 fF and
1 fF), runs `add_wire_caps.py` end to end, and checks that every emitted
capacitor, parsed with SPICE's scale suffixes, is the requested capacitance in
farads.  A second run checks the `--scale` factor.  No simulator is needed.

Fixtures:
  unit_roundtrip   scale 1.0:  2 fF and 1 fF nets -> 2e-15 F and 1e-15 F
  scale_roundtrip  scale 0.05: the same nets -> 1e-16 F and 5e-17 F
  json_total       the JSON summary reports the same 3 fF total and scale

Run:
  python3 tools/ro/test_add_wire_caps.py [--workdir runs/wirecap-fixtures]
          [--summary data/safe10/freeze/wirecap_generation_fixture.json]
Exit status is 0 only when every check behaves as declared.
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))

# SPICE scale suffixes, longest first so `meg`/`mil` win over `m`.
SUFFIXES = (("meg", 1e6), ("mil", 25.4e-6), ("t", 1e12), ("g", 1e9),
            ("k", 1e3), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9),
            ("p", 1e-12), ("f", 1e-15), ("a", 1e-18))

# The fixture loop: two inverters, two nets, known SPEF capacitance.
LOOP_SP = """.subckt RO_FIXTURE N1 N2
X_100_ N1 N2 sg13g2_inv_1
X_200_ N2 N1 sg13g2_inv_1
.ends RO_FIXTURE
"""

STDCELL_SP = """.subckt sg13g2_inv_1 A Y VDD VSS
X0 A Y VDD VSS sg13g2_inv_1_core
.ends sg13g2_inv_1
"""

# OpenRCX-style SPEF: *C_UNIT is pF, instance names are `*<num>` in *CONN and
# `<name>_<suffix>` in the loop deck, so the NAME_MAP is what joins them.
SPEF = """*SPEF "ieee 1481-1999"
*DESIGN "fixture"
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER []
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*1 _100_
*2 _200_
*3 N1
*4 N2

*D_NET *3 0.002
*CONN
*I *1:A I
*I *2:Y I
*CAP
*END

*D_NET *4 0.001
*CONN
*I *1:Y I
*I *2:A I
*CAP
*END
"""

# `*D_NET <net> <cap>` is in pF, so these are the fF the generator must emit.
EXPECTED_FF = {"N1": 2.0, "N2": 1.0}


def spice_farads(token):
    """(farads, suffix) for a SPICE numeric token; suffix '' means none."""
    t = token.strip().lower()
    for suf, mul in SUFFIXES:
        if t.endswith(suf):
            return float(t[:-len(suf)]) * mul, suf
    return float(t), ""


def parse_deck(path):
    """{node: (token, farads, suffix)} for every generated Cw<n> element."""
    caps = {}
    for line in open(path):
        toks = line.split()
        if len(toks) == 4 and toks[0].startswith("Cw") and toks[2] == "0":
            farads, suf = spice_farads(toks[3])
            caps[toks[1]] = (toks[3], farads, suf)
    return caps


def write_inputs(workdir):
    paths = dict(loop_sp=os.path.join(workdir, "loop_fixture.sp"),
                 stdcell_spice=os.path.join(workdir, "stdcell_fixture.sp"),
                 spef=os.path.join(workdir, "net_fixture.spef"))
    open(paths["loop_sp"], "w").write(LOOP_SP)
    open(paths["stdcell_spice"], "w").write(STDCELL_SP)
    open(paths["spef"], "w").write(SPEF)
    return paths


def run_generator(workdir, paths, scale):
    tag = f"s{scale:g}"
    out_sp = os.path.join(workdir, f"fixture_wirecap_{tag}.sp")
    out_json = os.path.join(workdir, f"fixture_wirecap_{tag}.json")
    cmd = [sys.executable, os.path.join(HERE, "add_wire_caps.py"),
           "--loop-sp", paths["loop_sp"],
           "--spef", paths["spef"],
           "--stdcell-spice", paths["stdcell_spice"],
           "--out", out_sp, "--json", out_json, "--scale", str(scale)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return out_sp, out_json, proc


def check_case(workdir, paths, scale):
    """One scale factor: every capacitor must round-trip to the right farads."""
    out_sp, out_json, proc = run_generator(workdir, paths, scale)
    checks = []
    if proc.returncode != 0:
        return dict(scale=scale, deck=out_sp, exit_code=proc.returncode,
                    checks=[dict(check="generator_exit", ok=False,
                                 detail=proc.stderr.strip()[:200])]), None
    caps = parse_deck(out_sp)
    for node, ff in sorted(EXPECTED_FF.items()):
        want = ff * scale * 1e-15
        tok, got, suf = caps.get(node, (None, None, None))
        checks.append(dict(
            check=f"cap_farads:{node}", ok=(
                got is not None and want > 0 and
                abs(got - want) / want < 1e-9),
            detail=f"deck token {tok!r} -> {got} F, want {want} F "
                   f"(suffix {suf!r})"))
        checks.append(dict(
            check=f"explicit_suffix:{node}", ok=bool(suf),
            detail=f"suffix {suf!r} in token {tok!r}"))
    summary = json.load(open(out_json)) if os.path.exists(out_json) else {}
    checks.append(dict(
        check="json_total_fF", ok=summary.get("total_wire_cap_fF") == 3.0,
        detail=f"total_wire_cap_fF={summary.get('total_wire_cap_fF')!r}"))
    checks.append(dict(
        check="json_scale", ok=summary.get("scale") == scale,
        detail=f"scale={summary.get('scale')!r}"))
    checks.append(dict(
        check="json_nets", ok=summary.get("nets_with_caps") == len(EXPECTED_FF),
        detail=f"nets_with_caps={summary.get('nets_with_caps')!r}"))
    row = dict(scale=scale, deck=out_sp, exit_code=proc.returncode,
               capacitors={k: v[0] for k, v in sorted(caps.items())},
               checks=checks)
    return row, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir",
                    default=os.path.join(REPO, "runs/wirecap-fixtures"))
    ap.add_argument("--summary",
                    default=os.path.join(REPO, "data/safe10/freeze",
                                         "wirecap_generation_fixture.json"))
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    paths = write_inputs(a.workdir)

    cases = []
    for scale in (1.0, 0.05):
        row, _ = check_case(a.workdir, paths, scale)
        cases.append(row)
    failed = [f"{c['scale']:g}:{chk['check']}"
              for c in cases for chk in c["checks"] if not chk["ok"]]
    summary = dict(
        tool="tools/ro/test_add_wire_caps.py",
        purpose="wire-capacitance generator fixture: emitted capacitors must "
                "parse back to the requested farads",
        loop_sp=paths["loop_sp"], spef=paths["spef"],
        expected_fF=EXPECTED_FF, cases=cases,
        passed=not failed, failures=failed)
    os.makedirs(os.path.dirname(a.summary), exist_ok=True)
    json.dump(summary, open(a.summary, "w"), indent=1)

    for c in cases:
        for chk in c["checks"]:
            print(f"  scale {c['scale']:<5g} {chk['check']:22s} "
                  f"ok={chk['ok']}  {chk['detail']}")
    print(f"summary: {a.summary}")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print(f"all {len(cases)} generator cases behaved as declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
