#!/usr/bin/env python3
"""Parse four OpenSTA reports and enforce the expected boundary-power order."""

import pathlib
import re
import sys


TOTAL = re.compile(
    r"^Total\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+100\.0%$", re.MULTILINE
)


def read_total(path):
    match = TOTAL.search(pathlib.Path(path).read_text(encoding="utf-8"))
    if not match:
        raise AssertionError(f"{path}: total power row not found")
    return tuple(float(value) for value in match.groups())


def main(paths):
    if len(paths) != 4:
        raise SystemExit("usage: analyze_power.py conventional.rpt dynamic8.rpt dynamic12.rpt dynamic16.rpt")
    totals = [read_total(path) for path in paths]
    names = ("conventional", "dynamic8", "dynamic12", "dynamic16")
    conventional = totals[0][3]

    assert conventional > 0
    assert totals[1][3] < totals[2][3] < totals[3][3] < conventional, (
        "total routed power does not increase monotonically with active boundary")

    print("mode,internal_W,switching_W,leakage_W,total_W,reduction_vs_conventional_pct")
    for name, values in zip(names, totals):
        reduction = 100.0 * (conventional - values[3]) / conventional
        print(f"{name},{values[0]:.12g},{values[1]:.12g},{values[2]:.12g},"
              f"{values[3]:.12g},{reduction:.6f}")
    print("PASS: annotated routed power increases monotonically with dynamic active width")


if __name__ == "__main__":
    main(sys.argv[1:])
