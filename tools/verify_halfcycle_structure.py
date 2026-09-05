#!/usr/bin/env python3
"""Assert preserved bank/RO connectivity and opposite-edge capture after routing."""
import json
from pathlib import Path
import re

import common as C

text = Path(C.netlist_path()).read_text()
cells = {}
for kind, name, body in re.findall(r"(sg13g2_\w+)\s+(\\?\S+)\s*\((.*?)\);", text, re.S):
    pins = {p: n.strip().lstrip("\\") for p, n in re.findall(r"\.(\w+)\(\s*([^)]*)\)", body)}
    cells[name.lstrip("\\")] = (kind, pins)
aliases = {a.lstrip("\\"): b.lstrip("\\") for a, b in
           re.findall(r"\bassign\s+(\S+)\s*=\s*(\S+)\s*;", text)}
buffers = {p["X"]: p["A"] for kind, p in cells.values() if kind.startswith("sg13g2_buf_")}

def canonical(net):
    seen = set()
    while net in aliases or net in buffers:
        assert net not in seen
        seen.add(net)
        net = aliases.get(net, buffers.get(net))
    return net

def same(a, b):
    assert canonical(a) == canonical(b), (a, b)

def pins(name):
    assert name in cells, name
    return cells[name][1]

def line(prefix, count):
    chain = [pins(f"{prefix}.g_inv[{i}].u_inv._cell") for i in range(count)]
    for i in range(count):
        assert cells[f"{prefix}.g_inv[{i}].u_inv._cell"][0] == "sg13g2_inv_1"
        if i:
            same(chain[i - 1]["Y"], chain[i]["A"])
    m0, m1, m2 = [pins(prefix + ".u_mux.u_m" + str(i)) for i in range(3)]
    for a, b in ((m0["A0"], chain[0]["A"]), (m0["A1"], chain[count//3-1]["Y"]),
                 (m1["A0"], chain[2*count//3-1]["Y"]), (m1["A1"], chain[-1]["Y"]),
                 (m2["A0"], m0["X"]), (m2["A1"], m1["X"])):
        same(a, b)
    return chain[0]["A"], m2["X"]

for seg in range(4):
    prefix = f"u_dut.g_seg[{seg}]"
    first, last = line(prefix + ".u_bank", 96)
    same(first, pins(prefix + ".g_fa[3].u_fa.u_o1")["X"])
    if seg < 3:
        same(last, pins(f"u_dut.g_seg[{seg+1}].g_fa[0].u_fa.u_a2")["A"])

for ro in ("gen", "mat"):
    prefix = "u_ro_" + ro
    gate = pins(prefix + ".u_gate.u_a3")
    if ro == "gen":
        first, last = line(prefix + ".u_line", 42)
        same(first, gate["X"])
    else:
        first, mid = line(prefix + ".u_line0", 66)
        second, last = line(prefix + ".u_line1", 66)
        same(first, gate["X"])
        same(mid, pins(prefix + ".u_f0.u_a2")["A"])
        same(second, pins(prefix + ".u_f0.u_o1")["X"])
        same(last, pins(prefix + ".u_f1.u_a2")["A"])
        last = pins(prefix + ".u_f1.u_o1")["X"]
    for i in range(8):
        p = pins(f"{prefix}.g_tail[{i}].u_t._cell")
        same(last, p["A"])
        last = p["Y"]
    close = pins(prefix + ".u_close._cell")
    same(last, close["A"])
    same(close["Y"], pins(prefix + ".u_gate.u_a2")["A"])
    same(pins(prefix + ".u_gate.u_a2")["X"], gate["B"])

# SG13G2 supplies positive-edge flops; the synthesized falling-edge bank
# must have an odd number of clock inversions from the top-level clock.
drivers = {p[k]: (kind, p) for kind, p in cells.values()
           for k in ("X", "Y") if k in p}
captures = []
for name, (kind, p) in cells.items():
    if not canonical(p.get("Q", "")).startswith("result_reg["):
        continue
    assert kind.startswith("sg13g2_df"), (name, kind)
    clock = p["CLK"]
    inversions = 0
    while canonical(clock) != "clk":
        clock = canonical(clock)
        k, cp = drivers[clock]
        assert k.startswith("sg13g2_inv_"), (clock, k)
        inversions += 1
        clock = cp["A"]
    assert inversions % 2 == 1, (name, inversions)
    captures.append(name)
assert len(captures) == 17

out = Path(C.DATA) / "verification/structure.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"run_id": C.RUN_ID, "build_commit": C.GIT_COMMIT,
                          "dut_bank_inverters": 384, "ro_loops": 2,
                          "falling_capture_flops": captures,
                          "passed": True}, indent=2) + "\n")
print("PASS: 384 bank inverters, all taps, both closed RO loops, 17 falling-edge captures")
