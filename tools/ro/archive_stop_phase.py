#!/usr/bin/env python3
"""Archive the stop-phase evidence for gate 3 from the existing waveforms.

Gate 3's remaining coverage question was whether the RO enable is closed at
enough phases of the ring's oscillation, and whether the resulting stop
transient can be captured inconsistently by the ripple stages.  Both halves are
observable in the archived window waveforms -- no new simulation is needed:

  * the phase at gate close (`measure_stop_phase`), per case;
  * the stop transient itself (`classify_stop_transient`): every rising crossing
    of the loop node is classified by pulse amplitude, so a marginal-width
    ("runt") pulse on the counter's clock is counted explicitly.

This tool walks the three archived window case sets, derives the rail from each
case's corner name, and writes one machine-readable dataset.  It reuses the two
analysis tools rather than re-implementing them.

Usage:
  archive_stop_phase.py --runs runs/freeze-validation \
      --json data/safe10/freeze/stop_phase_coverage.json
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import classify_stop_transient as cls  # noqa: E402
import measure_stop_phase as msp  # noqa: E402


def vdd_from_name(path):
    """Rail voltage from a rawfile name (`nom_typ_1p20V_25C` -> 1.20)."""
    m = re.search(r"_(\d)p(\d+)V_", os.path.basename(path))
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


def loop_node_from_name(path, nodes):
    """`(loop_node, canary_key)` for a rawfile, from the canary and sel in its name.

    The tail selectors share one loop node per canary (`ro_gen_sel0..3` are all
    `_1347_/CLK`), so the canary prefix is what selects the node; the returned
    key keeps the selection so the per-configuration grouping stays honest.
    """
    m = re.search(r"(ro_gen|ro_mat)_sel(\d)", os.path.basename(path))
    if not m:
        return None, None
    canary, sel = m.group(1), m.group(2)
    for node, key in nodes.items():
        if key.startswith(canary + "_"):
            return node, f"{canary}_sel{sel}"
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=os.path.join(REPO, "runs/freeze-validation"))
    ap.add_argument("--loopdir", default=os.path.join(REPO, "runs/count-loops"))
    ap.add_argument("--json", default=os.path.join(
        REPO, "data/safe10/freeze", "stop_phase_coverage.json"))
    a = ap.parse_args()
    nodes = msp.measure_tree(a.loopdir)

    sets = {
        "primary": sorted(glob.glob(os.path.join(a.runs, "primary/cases/*.raw"))),
        "matrix": sorted(glob.glob(os.path.join(a.runs, "matrix/cases/*.raw"))),
        "control": sorted(glob.glob(os.path.join(a.runs, "control/*.raw"))),
    }
    rows = []
    for name, files in sets.items():
        for f in files:
            vdd = vdd_from_name(f)
            node, canary = loop_node_from_name(f, nodes)
            if vdd is None or node is None:
                rows.append(dict(case_set=name, raw=os.path.basename(f),
                                 error="cannot resolve rail or loop node"))
                continue
            ph = msp.measure(f, vdd, node)
            tr = cls.classify(f, vdd, node)
            row = dict(case_set=name, canary=canary, loop_node=node,
                       vdd=vdd, raw=os.path.basename(f))
            for src in (ph, tr):
                for k, v in src.items():
                    if k not in ("raw", "vdd", "loop_node", "last_pulse_peaks_over_vdd"):
                        row[k] = v
            rows.append(row)

    good = [r for r in rows if "stop_phase" in r and "n_rise_crossings" in r]
    phases = sorted(r["stop_phase"] for r in good)
    # Per-configuration phase spread: the three "startup phases" of a
    # configuration are expected to share one phase, so the spread within a
    # group is the evidence for that claim.
    groups = {}
    for r in good:
        key = f"{r['canary']}@{r['period_ns']}ns"
        groups.setdefault(key, []).append(r["stop_phase"])
    by_config = [dict(config=k, n=len(v), phases=sorted(v),
                      spread=round(max(v) - min(v), 4))
                 for k, v in sorted(groups.items())]
    summary = dict(
        tool="tools/ro/archive_stop_phase.py",
        purpose="gate 3 stop-phase and stop-transient evidence from the "
                "archived window waveforms (no new simulation)",
        n_cases=len(rows), n_measured=len(good),
        stop_phase_min=round(phases[0], 4) if phases else None,
        stop_phase_max=round(phases[-1], 4) if phases else None,
        stop_phase_spread=round(phases[-1] - phases[0], 4) if phases else None,
        n_distinct_phases=len(set(phases)),
        total_rise_crossings=sum(r["n_rise_crossings"] for r in good),
        total_runt_pulses=sum(r["n_runt"] for r in good),
        total_noise_glitches=sum(r["n_noise"] for r in good),
        total_crossings_after_close=sum(r["crossings_after_close"] for r in good),
        by_configuration=by_config,
        cases=rows)
    os.makedirs(os.path.dirname(a.json), exist_ok=True)
    json.dump(summary, open(a.json, "w"), indent=1, default=str)
    print(json.dumps({k: summary[k] for k in
                      ("n_cases", "n_measured", "stop_phase_min",
                       "stop_phase_max", "stop_phase_spread",
                       "n_distinct_phases", "total_rise_crossings",
                       "total_runt_pulses", "total_noise_glitches",
                       "total_crossings_after_close")}, indent=1))
    print("\nper-configuration stop phase (three startups each where present):")
    for g in by_config:
        print(f"  {g['config']:28s} n={g['n']} spread={g['spread']:.4f} "
              f"phases={g['phases']}")
    print("wrote " + a.json)
    return 0 if good else 2


if __name__ == "__main__":
    sys.exit(main())
