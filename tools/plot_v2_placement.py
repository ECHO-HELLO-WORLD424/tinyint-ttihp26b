#!/usr/bin/env python3
"""Render v2 CI placement from final DEF/netlist and the pinned PDK LEF.

Inside the devcontainer:
python tools/plot_v2_placement.py --inputs runs/v2-blog-input --lef PDK_STDCELL_LEF
Inputs are final.def/final.v from GDS_logs of CI run 34158224984.
The unmodified gds_render artifact is docs/figures/v2/gds-render-ci.png.
"""
import argparse
import collections
import csv
import hashlib
import json
import re
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch
from matplotlib.collections import PatchCollection

p = argparse.ArgumentParser()
p.add_argument("--inputs", type=Path, required=True)
p.add_argument("--lef", type=Path, required=True)
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
out = root / "docs/figures/v2"
defpath, nlpath = a.inputs / "final.def", a.inputs / "final.v"
d, n, lef = defpath.read_text(), nlpath.read_text(), a.lef.read_text()
sizes = {}
for name, body in re.findall(r"^MACRO\s+(\S+)(.*?)^END\s+\1\s*$", lef, re.S | re.M):
    match = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", body)
    if match:
        sizes[name] = tuple(map(float, match.groups()))
cells = {}
for kind, name, body in re.findall(r"(sg13g2_\w+)\s+(\\?\S+)\s*\((.*?)\);", n, re.S):
    pins = {k: v.strip().lstrip("\\") for k,v in re.findall(r"\.(\w+)\(\s*([^)]*)\)", body)}
    cells[name.lstrip("\\")] = (kind, pins)

# Conservative attribution: no claim that ABC-flattened gates form separate blocks.
palette = {
    "DUT carry cells + delay banks": "#0097b2",
    "Generic RO + counter state": "#713bd1",
    "Matched RO + counter state": "#d12b8f",
    "One-shot capture flops": "#ee9800",
    "Named pattern-state flops": "#139653",
    "Control / window / readout state": "#2463ce",
    "Error-accounting state": "#d94c35",
    "Other logic (includes oracle)": "#8295aa",
    "Physical-only cells": "#e2e6ec",
}
def category(name, master):
    kind, pins = cells.get(name, (master, {}))
    q = pins.get("Q", "")
    if any(x in master for x in ("fill", "tap", "decap")):
        return "Physical-only cells"
    if name.startswith("u_dut."):
        return "DUT carry cells + delay banks"
    for prefix, label in [("u_ro_gen.", "Generic RO + counter state"), ("u_ro_mat.", "Matched RO + counter state")]:
        if name.startswith(prefix) or q.startswith(prefix):
            return label
    if kind.startswith("sg13g2_df"):
        if q.startswith("result_reg["):
            return "One-shot capture flops"
        if q.startswith("u_pat."):
            return "Named pattern-state flops"
        if q.startswith(("err_cnt[", "err_dut_b[")) or q == "err_seen":
            return "Error-accounting state"
        if q.startswith(("ops_cnt[", "frame_cnt[", "cfg[", "boot[", "win_cnt[", "can_sel[", "uo_out[")) or q in ("started", "capture_pending", "win_done"):
            return "Control / window / readout state"
    if name not in cells:
        assert any(x in master for x in ("fill", "tap", "decap")), (name, master)
        return "Physical-only cells"
    return "Other logic (includes oracle)"

units = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", d)[1])
die = list(map(int, re.search(r"DIEAREA \( (\d+) (\d+) \) \( (\d+) (\d+) \)",d).groups()))
body = d.split("COMPONENTS ",1)[1].split("END COMPONENTS",1)[0]
rows = []
for name, master, x, y, orient in re.findall(r"- (\S+) (\S+)(?: \+ SOURCE \S+)? \+ (?:PLACED|FIXED) \( (\d+) (\d+) \) (\S+)\s*;",body):
    name = name.replace("\\", "")
    w,h = sizes[master]
    if orient in ("E", "W", "FE", "FW"):
        w,h = h,w
    rows.append(dict(instance=name, master=master, x_um=int(x)/units, y_um=int(y)/units,
                     width_um=w, height_um=h, category=category(name,master)))
assert len(rows) == int(body.split(";",1)[0]), "DEF parser missed components"
counts = collections.Counter(r["category"] for r in rows)
assert counts["DUT carry cells + delay banks"] == 476
assert counts["One-shot capture flops"] == 17
with (out / "placement-cells.csv").open("w",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)

fig, (raw, ax) = plt.subplots(1,2,figsize=(15,8.6))
raw.imshow(plt.imread(out / "gds-render-ci.png")); raw.axis("off")
raw.set_title("Routed GDS · original workflow render", fontsize=14, pad=14)
for label,color in palette.items():
    patches=[Rectangle((r["x_um"],r["y_um"]),r["width_um"],r["height_um"]) for r in rows if r["category"]==label]
    ax.add_collection(PatchCollection(patches, facecolor=color, edgecolor="white", linewidth=.15))
ax.set(xlim=(die[0]/units,die[2]/units),ylim=(die[1]/units,die[3]/units),aspect="equal",
       xlabel="x (µm)",ylabel="y (µm)")
ax.set_title("Placed cells · colors correspond to RTL components", fontsize=14,pad=14)
fig.suptitle("V2 physical implementation · CI run 34158224984", fontsize=19,fontweight="bold",y=.98)
fig.legend(handles=[Patch(color=c,label=f"{k} ({counts[k]})") for k,c in palette.items()],
           loc="lower center", bbox_to_anchor=(.5,.06),ncol=3,fontsize=10,frameon=False)
fig.text(.5,.025,"202.08 × 154.98 µm die · cell rectangles use final DEF coordinates and PDK LEF sizes · legend counts are instances",ha="center",fontsize=10)
fig.subplots_adjust(top=.91,bottom=.25,wspace=.16,left=.025,right=.985)
fig.savefig(out / "placement-map.png",dpi=180)
fig.savefig(out / "placement-map.svg")
inputs={"final.def":defpath,"final.v":nlpath,"sg13g2_stdcell.lef":a.lef,"gds_render.png":out/"gds-render-ci.png"}
manifest={"run_id":34158224984,"commit":"b9f03f798978840c8bdc2bb574877408e0f33f4c",
          "run_url":"https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/34158224984",
          "artifacts":["GDS_logs","gds_render"],"pdk_revision":"c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c",
          "inputs_sha256":{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in inputs.items()},
          "instance_counts":dict(counts),"matplotlib_version":matplotlib.__version__,
          "classification":"Preserved hierarchy for DUT/RO cells; flop Q nets for named state. Unattributed flattened logic, including the oracle, stays in Other logic. This does not assign exclusive floorplan regions to modules."}
(out/"placement-provenance.json").write_text(json.dumps(manifest,indent=2)+"\n")
print(json.dumps(dict(counts),indent=2))
