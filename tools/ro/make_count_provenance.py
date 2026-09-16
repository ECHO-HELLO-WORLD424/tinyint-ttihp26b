#!/usr/bin/env python3
"""Write provenance.json for the counter-inclusive RO transient dataset.

Everything needed to reproduce or audit the dataset in one place: the design
revision and extracted netlist, the PDK and toolchain identity, the simulation
settings, a hash of every data file, and the cross-check against the f_osc
dataset.

Usage:
  make_count_provenance.py --countdir data/safe10/count \
      --netlist <extracted>.spice --commit <sha> --ci-run <id> \
      --fosc data/safe10/spice/spice_ro.csv --stdcell-sha256 <sha> \
      --out data/safe10/count/provenance.json
"""

import argparse
import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--countdir", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--netlist", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--ci-run", required=True)
    ap.add_argument("--branch", default="proposal-canary")
    ap.add_argument("--tool-image", default=None)
    ap.add_argument("--pdk-rev", default=None)
    ap.add_argument("--stdcell-sha256", default=None)
    ap.add_argument("--fosc", default=None)
    ap.add_argument("--created", default=None)
    ap.add_argument("--extra", default=None,
                    help="JSON object merged into the record")
    a = ap.parse_args()

    out = a.out or os.path.join(a.countdir, "provenance.json")
    prov = {
        "kind": "counter-inclusive extracted RO transient (SPICE) validation",
        "created": a.created or os.environ.get("SOURCE_DATE") or "",
        "revision": 1,
        "purpose": ("show that the canary's ripple edge counter counts the ring's "
                    "edges at speed; the f_osc dataset holds the counter in reset "
                    "and cannot answer this"),
        "design": {
            "source_commit": a.commit,
            "branch": a.branch,
            "ci_run": a.ci_run,
            "ci_run_url": ("https://github.com/ECHO-HELLO-WORLD424/"
                           "tinyint-ttihp26b/actions/runs/%s" % a.ci_run),
            "extracted_netlist": os.path.basename(a.netlist),
            "extracted_netlist_sha256": sha256(a.netlist),
            "tool_image": a.tool_image,
            "pdk_rev": a.pdk_rev,
        },
        "tools": {
            "extract": "tools/ro/extract_ro_loop.py --counter",
            "deck": "tools/ro/run_ro_count_case.py",
            "sweep": "tools/ro/sweep_ro_count.py",
            "analyse": "tools/ro/analyse_ro_count.py",
            "compare": "tools/ro/compare_ro_count.py",
            "stdcell_spice_sha256": a.stdcell_sha256,
        },
        "method": {
            "extraction": ("ring subtree plus the full 16-stage ripple counter, "
                           "its toggle inverters, clock drivers and the reset "
                           "buffer tree walked back to rst_n"),
            "deck": ("reset driven as PWL (assert then release); all 16 counter "
                     "bits saved; counter outputs never driven; X-instance node "
                     "order taken from the .subckt declaration"),
            "analysis": ("period from the loop node; counter decoded after "
                         "bit 0's last falling edge; checked against ring edges, "
                         "the period estimate, and per-stage ripple rates"),
        },
        "files": {},
    }
    for name in sorted(os.listdir(a.countdir)):
        path = os.path.join(a.countdir, name)
        if not os.path.isfile(path) or name == "provenance.json":
            continue
        if name.endswith((".csv", ".json", ".png")):
            prov["files"][name] = sha256(path)
    if a.fosc and os.path.exists(a.fosc):
        prov["comparison_with_fosc"] = {
            "fosc_dataset": os.path.relpath(a.fosc, os.path.dirname(out)),
            "fosc_dataset_sha256": sha256(a.fosc),
            "cross_check": "count_vs_fosc.json",
        }
    if a.extra:
        with open(a.extra) as fh:
            prov.update(json.load(fh))
    with open(out, "w") as fh:
        json.dump(prov, fh, indent=1)
    print(f"wrote {out}")
    print(json.dumps(prov["files"], indent=1))


if __name__ == "__main__":
    main()
