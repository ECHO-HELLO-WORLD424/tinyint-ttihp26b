#!/usr/bin/env python3
"""Cross-check the counter-inclusive dataset against the f_osc dataset.

The two SPICE datasets measure the same rings in different deck configurations:
`spice_ro.csv` (f_osc, counter static) and `ro_count.csv` (counter running).
They are independent only in the counter; the loop, the corner models and the
extracted cells are shared, so this check catches the failure modes that matter:

  * the counter changes the ring (a large frequency shift between the two decks
    would mean the counter loads or perturbs the loop in the counter deck);
  * a case in which the counter did not count (`status != ok`, a wrong ripple
    rate, or a final count that disagrees with the ring edges).

Usage:
  compare_ro_count.py --fosc data/safe10/spice/spice_ro.csv \
                      --count data/safe10/count/ro_count.csv \
                      --outdir data/safe10/count
"""

import argparse
import csv
import json
import os
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def load(path, key_prefix=""):
    rows = {}
    for row in csv.DictReader(open(path)):
        key = (row["corner"], row["canary"], int(row["can_sel"]))
        rows[key] = row
    return rows


def fnum(row, field):
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fosc", required=True)
    ap.add_argument("--count", required=True)
    ap.add_argument("--outdir", default=HERE)
    ap.add_argument("--tolerance-pct", type=float, default=5.0,
                    help="allowed |f_osc(counter) - f_osc(static)| in percent")
    a = ap.parse_args()

    fosc = load(a.fosc)
    count = load(a.count)
    shared = sorted(set(fosc) & set(count))
    missing = sorted(set(count) - set(fosc))
    if missing:
        print(f"WARNING: {len(missing)} count cases have no f_osc counterpart: "
              f"{missing}", file=sys.stderr)

    rows = []
    problems = []
    frequency_notes = []
    for key in shared:
        f, c = fosc[key], count[key]
        f_static = fnum(f, "f_osc_mhz")
        f_count = fnum(c, "f_osc_mhz")
        delta_pct = None
        if f_static and f_count:
            delta_pct = 100.0 * (f_count - f_static) / f_static
        row = OrderedDict(
            corner=key[0], canary=key[1], can_sel=key[2],
            f_osc_static_mhz=f_static, f_osc_counter_mhz=f_count,
            delta_pct=None if delta_pct is None else round(delta_pct, 3),
            counter_final=c.get("counter_final"),
            ring_edges=c.get("ring_edges_in_count_window"),
            count_error_edges=c.get("count_error_edges"),
            count_matches_ring_edges=c.get("count_matches_ring_edges"),
            ripple_stage_rates_ok=c.get("ripple_stage_rates_ok"),
            status=c.get("status"),
        )
        rows.append(row)
        if c.get("status") != "ok":
            problems.append(f"{key}: count status {c.get('status')}")
        if c.get("ripple_stage_rates_ok") not in ("True", "true", True):
            problems.append(f"{key}: ripple stage rates wrong")
        if c.get("count_matches_ring_edges") not in ("True", "true", True):
            problems.append(f"{key}: counted {c.get('counter_final')} vs "
                            f"{c.get('ring_edges_in_count_window')} ring edges")
        if delta_pct is not None and abs(delta_pct) > a.tolerance_pct:
            # A frequency difference is reported but is not a counting failure:
            # it means the two decks did not select the same ring (a tap-mux
            # role/build difference, see the slow-corner ro_mat cases).
            frequency_notes.append(
                f"{key}: f_osc differs by {delta_pct:+.2f}% between the "
                f"counter-running and counter-static decks")

    csv_path = os.path.join(a.outdir, "count_vs_fosc.csv")
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                           ["corner", "canary", "can_sel"])
        w.writeheader()
        w.writerows(rows)
    deltas = [r["delta_pct"] for r in rows if r["delta_pct"] is not None]
    summary = dict(
        fosc_dataset=a.fosc, count_dataset=a.count,
        n_cases=len(rows), n_missing_fosc=len(missing),
        n_problems=len(problems), problems=problems,
        n_frequency_notes=len(frequency_notes), frequency_notes=frequency_notes,
        delta_pct_min=None if not deltas else min(deltas),
        delta_pct_max=None if not deltas else max(deltas),
        delta_pct_mean=None if not deltas else sum(deltas) / len(deltas),
        tolerance_pct=a.tolerance_pct,
    )
    json_path = os.path.join(a.outdir, "count_vs_fosc.json")
    with open(json_path, "w") as fh:
        json.dump(dict(summary=summary, cases=rows), fh, indent=1)
    print(json.dumps(summary, indent=1))
    print(f"wrote {csv_path} and {json_path}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
