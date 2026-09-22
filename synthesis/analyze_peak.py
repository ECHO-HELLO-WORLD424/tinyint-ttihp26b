#!/usr/bin/env python3
"""Aggregate windowed OpenSTA power reports into a cycle-peak summary.

Reads the candidate windows produced by ``peak_activity.py`` and the matching
``peak_power.tcl`` reports, then reports the peak cycle-average power for each
architecture mode next to the whole-trace average power. Every candidate report
must be fully annotation-validated (nonzero annotated pins, zero unannotated).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

TOTAL_RE = re.compile(
    r"^Total\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+100\.0%$", re.MULTILINE
)
ANNOTATED_RE = re.compile(r"^Annotated\s+(\d+)\s+pin activities\.$", re.MULTILINE)
UNANNOTATED_RE = re.compile(r"^unannotated\s+(\d+)\s*$", re.MULTILINE)


def read_total(path):
    match = TOTAL_RE.search(open(path, encoding="utf-8").read())
    if not match:
        raise AssertionError("{}: total power row not found".format(path))
    internal, switching, leakage, total = (
        float(match.group(1)), float(match.group(2)),
        float(match.group(3)), float(match.group(4)),
    )
    return internal, switching, leakage, total


def check_annotation(log_path):
    text = open(log_path, encoding="utf-8").read()
    annotated = ANNOTATED_RE.search(text)
    unannotated = UNANNOTATED_RE.search(text)
    if annotated is None or unannotated is None:
        raise AssertionError("{}: activity annotation report missing".format(log_path))
    if int(annotated.group(1)) <= 0:
        raise AssertionError("{}: no annotated pins".format(log_path))
    if int(unannotated.group(1)) != 0:
        raise AssertionError("{}: {} unannotated pins".format(
            log_path, unannotated.group(1)))
    return int(annotated.group(1))


def load_candidates(path):
    with open(path, encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peakdir", required=True)
    parser.add_argument("--powerdir", required=True)
    parser.add_argument("--modes", default="mode0,mode1,mode2,mode3")
    parser.add_argument("--summary", default=None)
    args = parser.parse_args(argv)

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    rows = []
    for mode in modes:
        candidates = load_candidates(
            os.path.join(args.peakdir, "{}.candidates.csv".format(mode))
        )
        average_internal, average_switching, average_leakage, average_total = (
            read_total(os.path.join(args.powerdir, "{}.power.rpt".format(mode)))
        )
        annotated_counts = set()
        windows = []
        for candidate in candidates:
            slice_name = candidate["slice"]
            report = os.path.join(args.peakdir, "{}.rpt".format(slice_name))
            log = os.path.join(args.peakdir, "{}.log".format(slice_name))
            if not os.path.exists(report):
                raise AssertionError("missing power report {}".format(report))
            annotated_counts.add(check_annotation(log))
            internal, switching, leakage, total = read_total(report)
            windows.append(
                {
                    "rank": int(candidate["rank"]),
                    "window": int(candidate["window"]),
                    "begin_ps": int(candidate["begin_ps"]),
                    "end_ps": int(candidate["end_ps"]),
                    "flips": int(candidate["flips"]),
                    "energy_fJ": float(candidate["energy_fJ"]),
                    "internal_W": internal,
                    "switching_W": switching,
                    "leakage_W": leakage,
                    "total_W": total,
                }
            )
        if not windows:
            raise AssertionError("{}: no candidate windows measured".format(mode))
        if len(annotated_counts) != 1:
            raise AssertionError(
                "{}: inconsistent annotated pin counts {}".format(
                    mode, sorted(annotated_counts))
            )
        peak = max(windows, key=lambda item: item["total_W"])
        rows.append(
            {
                "mode": mode,
                "average_W": average_total,
                "average_switching_W": average_switching,
                "peak_W": peak["total_W"],
                "peak_switching_W": peak["switching_W"],
                "peak_over_average": peak["total_W"] / average_total,
                "peak_window": peak["window"],
                "peak_begin_ps": peak["begin_ps"],
                "peak_end_ps": peak["end_ps"],
                "peak_flips": peak["flips"],
                "annotated_pins": sorted(annotated_counts)[0],
                "candidates": windows,
            }
        )
        # Persist the full ranked per-window table for this mode.
        detail_path = os.path.join(args.peakdir, "{}.peak_windows.csv".format(mode))
        with open(detail_path, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "rank", "window", "begin_ps", "end_ps", "flips",
                    "energy_fJ", "internal_W", "switching_W", "leakage_W",
                    "total_W",
                ],
            )
            writer.writeheader()
            for entry in sorted(windows, key=lambda item: item["total_W"], reverse=True):
                writer.writerow(entry)

    summary_path = args.summary or os.path.join(args.peakdir, "peak_summary.csv")
    with open(summary_path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "mode", "average_W", "peak_W", "peak_over_average",
            "peak_window", "peak_begin_ps", "peak_end_ps",
            "average_switching_W", "peak_switching_W", "annotated_pins",
        ])
        for row in rows:
            writer.writerow([
                row["mode"], "{:.9g}".format(row["average_W"]),
                "{:.9g}".format(row["peak_W"]),
                "{:.6f}".format(row["peak_over_average"]),
                row["peak_window"], row["peak_begin_ps"], row["peak_end_ps"],
                "{:.9g}".format(row["average_switching_W"]),
                "{:.9g}".format(row["peak_switching_W"]),
                row["annotated_pins"],
            ])

    print("mode,average_uW,peak_uW,peak/average,peak_window,annotated_pins")
    for row in rows:
        print(
            "{mode},{avg:.3f},{peak:.3f},{ratio:.3f},{window},{pins}".format(
                mode=row["mode"], avg=row["average_W"] * 1e6,
                peak=row["peak_W"] * 1e6, ratio=row["peak_over_average"],
                window=row["peak_window"], pins=row["annotated_pins"],
            )
        )
    print("summary: {}".format(summary_path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
