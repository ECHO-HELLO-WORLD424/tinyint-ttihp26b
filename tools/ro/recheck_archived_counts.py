#!/usr/bin/env python3
"""Re-check archived RO count waveforms against the current analyzer.

The archived datasets under `data/safe10/freeze/` were analysed by the analyzer
revision current at the time.  Gate 1 later gained a readout-level requirement
(a counter bit must be at a valid logic low/high at the decode point, not merely
quiet: the 50 % decode threshold classifies a mid-rail node as a logic 0).  This
tool re-derives the decode-point level of every saved counter bit from the raw
waveforms the archived verdicts rest on, and with `--full` re-runs the whole
analyzer on each waveform so any verdict change is visible.

The rawfiles live under `runs/` (git-ignored, large), so this tool is not part
of the fast `tools/verify_freeze.sh` re-check; it is run when the waveforms are
present.  Its output is archived as
`data/safe10/freeze/analyzer_recheck.json`.

Usage:
  recheck_archived_counts.py [--runs runs/freeze-validation]
      [--json data/safe10/freeze/analyzer_recheck.json]
      [--full] [--limit N]
"""

import argparse
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import analyse_ro_count as ana  # noqa: E402
import analyse_spice_raw as raw_io  # noqa: E402

BITS = ana.N_BITS


def bit_indices(names):
    """{bit: column index} using the same name match as the analyzer."""
    bits = {}
    for i, n in enumerate(names):
        low = n.lower().strip()
        for b in range(BITS):
            if low in (f"v(q{b})", f"v(x1.q{b})", f"v(sense_q{b})"):
                bits[b] = i
    return bits


def level_case(raw, decode_ns, vdd, guard_ns=1.0):
    """Decode-point levels of all 16 bits, without the edge scans."""
    names, cols = raw_io.read_raw(raw)
    times = cols[0]
    # Older analyzer revisions did not record the decode time; the rule is the
    # end of the run minus the settle guard.
    if decode_ns is None:
        decode_ns = (times[-1] - guard_ns * 1e-9) * 1e9
    t = decode_ns * 1e-9
    bits = bit_indices(names)
    missing = sorted(set(range(BITS)) - set(bits))
    per_bit = {}
    for b in sorted(bits):
        v = ana.value_at(times, cols[bits[b]], t)
        per_bit[b] = dict(level_v=round(v, 4),
                          level_valid=ana.level_valid(v, vdd))
    invalid = [b for b in sorted(per_bit) if not per_bit[b]["level_valid"]]
    return dict(n_bits_saved=len(bits), missing_bits=missing,
                levels_v={str(b): per_bit[b]["level_v"] for b in per_bit},
                invalid_level_bits=invalid, levels_valid=not invalid,
                min_level_v=min((d["level_v"] for d in per_bit.values()),
                                default=None),
                max_level_v=max((d["level_v"] for d in per_bit.values()),
                                default=None))


# Verdict fields every archived revision records.  `levels_valid` /
# `invalid_level_bits` are the fields this re-check adds, so they are reported
# but excluded from the before/after equality test against an older revision.
BASE_FIELDS = ("status", "settled", "count_ok", "counter_final",
               "ring_edges_in_window", "unsettled_bits", "unexercised_bits",
               "coverage_complete", "rate_stable")
NEW_FIELDS = ("levels_valid", "invalid_level_bits")


def verdict_fields(d):
    out = {k: d.get(k) for k in BASE_FIELDS}
    out.update({k: d.get(k) for k in NEW_FIELDS})
    return out


def load_baseline(path):
    """Import a baseline analyzer revision for an A/B run on the same rawfile.

    The baseline's own `analyse()` is used, so the comparison isolates the
    change under test from every earlier revision of the tool that may have
    produced the stored JSONs.
    """
    import importlib.util
    d = os.path.dirname(os.path.abspath(path))
    sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location("baseline_analyse_ro_count",
                                                  path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_cases(runs):
    """(jsonfile, rawfile, analyzer-record) for every stored analyzer result.

    Some archives keep one dict per file, others (the carry and control runs) a
    list of dicts in a single `*_result.json`.
    """
    out = []
    for f in sorted(glob.glob(os.path.join(runs, "**", "*.json"),
                              recursive=True)):
        try:
            doc = json.load(open(f))
        except (ValueError, OSError):
            continue
        entries = doc if isinstance(doc, list) else [doc]
        for d in entries:
            if not isinstance(d, dict) or "count_ok" not in d \
                    or "status" not in d:
                continue
            raw = d.get("raw") or f[:-5] + ".raw"
            if not os.path.isabs(raw):
                raw = os.path.join(REPO, raw)
            if not os.path.exists(raw):
                continue
            out.append((f, raw, d))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=os.path.join(REPO, "runs/freeze-validation"))
    ap.add_argument("--json",
                    default=os.path.join(REPO, "data/safe10/freeze",
                                         "analyzer_recheck.json"))
    ap.add_argument("--full", action="store_true",
                    help="re-run the whole analyzer on every waveform")
    ap.add_argument("--limit", type=int, default=0,
                    help="analyse at most N cases (0 = all)")
    ap.add_argument("--match", default=None,
                    help="only cases whose tag contains this substring")
    ap.add_argument("--baseline", default=None,
                    help="analyzer revision (path to analyse_ro_count.py) to "
                         "A/B against; its decode_guard/window rules are shared")
    ap.add_argument("--merge", nargs="*", default=None,
                    help="merge these per-partition recheck JSONs into --json "
                         "instead of analysing waveforms")
    a = ap.parse_args()
    baseline = load_baseline(a.baseline) if a.baseline else None

    if a.merge:
        rows = []
        modes = set()
        for p in a.merge:
            part = json.load(open(p))
            rows.extend(part["cases"])
            modes.add(part["mode"])
        invalid = [r["tag"] for r in rows if not r["levels_valid"]]
        changed = [r["tag"] for r in rows if r.get("verdict_changed")]
        summary = dict(
            tool="tools/ro/recheck_archived_counts.py",
            mode="+".join(sorted(modes)), runs=os.path.relpath(a.runs, REPO),
            n_cases=len(rows), all_levels_valid=not invalid,
            invalid_level_cases=invalid, verdict_changes=changed,
            level_band=dict(low_fraction=ana.LEVEL_LOW_FRACTION,
                            high_fraction=ana.LEVEL_HIGH_FRACTION),
            merged_from=[os.path.relpath(p, REPO) for p in a.merge],
            cases=sorted(rows, key=lambda r: r["tag"]))
        os.makedirs(os.path.dirname(a.json), exist_ok=True)
        json.dump(summary, open(a.json, "w"), indent=1)
        print(f"merged {len(rows)} rechecked cases from {len(a.merge)} parts; "
              f"levels valid in {len(rows) - len(invalid)}/{len(rows)}; "
              f"verdict changes: {len(changed)}")
        print("wrote " + a.json)
        return 0 if not invalid and not changed else 1

    cases = find_cases(a.runs)
    if a.match:
        cases = [c for c in cases
                 if a.match in (c[2].get("tag") or os.path.basename(c[0]))]
    if a.limit:
        cases = cases[:a.limit]
    rows = []
    for f, raw, d in cases:
        vdd = d.get("vdd")
        if vdd is None:
            vdd = (d.get("case") or {}).get("vdd", 1.2)
        decode_ns = d.get("decode_time_ns")
        guard_ns = d.get("counter_final_settle_guard_ns") or 1.0
        row = dict(json=os.path.relpath(f, REPO),
                   tag=d.get("tag") or os.path.basename(f)[:-5],
                   vdd=vdd, decode_time_ns=decode_ns,
                   settle_guard_ns=guard_ns)
        t0 = time.time()
        lv = level_case(raw, decode_ns, vdd, guard_ns)
        row.update(lv)
        if a.full:
            new = ana.analyse(raw, vdd, d.get("loop_node"),
                              decode_guard_ns=guard_ns, dump_edges=False)
            before = (baseline.analyse(raw, vdd, d.get("loop_node"),
                                       decode_guard_ns=guard_ns,
                                       dump_edges=False)
                      if baseline else d)
            row["baseline"] = (os.path.relpath(a.baseline, REPO)
                               if baseline else "stored_json")
            row["stored_status"] = d.get("status")
            before_f = verdict_fields(before)
            after_f = verdict_fields(new)
            row["before"] = {k: before_f[k] for k in BASE_FIELDS}
            row["after"] = after_f
            row["verdict_changed"] = bool(
                {k: before_f[k] for k in BASE_FIELDS} !=
                {k: after_f[k] for k in BASE_FIELDS})
        row["wall_s"] = round(time.time() - t0, 1)
        rows.append(row)
        flags = " verdict_changed" if row.get("verdict_changed") else ""
        flags += " INVALID_LEVEL" if not row["levels_valid"] else ""
        print(f"  {row['tag']:64s} bits={lv['n_bits_saved']:2d} "
              f"levels={lv['min_level_v']}..{lv['max_level_v']} "
              f"valid={lv['levels_valid']}{flags}", flush=True)

    invalid = [r["tag"] for r in rows if not r["levels_valid"]]
    changed = [r["tag"] for r in rows if r.get("verdict_changed")]
    summary = dict(
        tool="tools/ro/recheck_archived_counts.py",
        mode="full-analyzer" if a.full else "decode-levels-only",
        runs=os.path.relpath(a.runs, REPO),
        match=a.match,
        n_cases=len(rows),
        all_levels_valid=not invalid,
        invalid_level_cases=invalid,
        verdict_changes=changed,
        level_band=dict(low_fraction=ana.LEVEL_LOW_FRACTION,
                        high_fraction=ana.LEVEL_HIGH_FRACTION),
        cases=rows)
    os.makedirs(os.path.dirname(a.json), exist_ok=True)
    json.dump(summary, open(a.json, "w"), indent=1)
    print(f"\n{len(rows)} archived cases rechecked; levels valid in "
          f"{len(rows) - len(invalid)}/{len(rows)}; "
          f"verdict changes: {len(changed)}")
    print("wrote " + a.json)
    return 0 if not invalid and not changed else 1


if __name__ == "__main__":
    sys.exit(main())
