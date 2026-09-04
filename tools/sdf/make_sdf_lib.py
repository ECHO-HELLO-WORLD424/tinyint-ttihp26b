#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Build a timing-safe Verilog library for SDF-annotated simulation.

The IHP stdcell Verilog models pair IOPATH arcs with timing checks
($setuphold/$recrem/$width) whose delayed_* placeholder nets are only driven
by the check machinery. Icarus Verilog cannot execute those checks (the
delayed nets stay X and poison every flip-flop), and full specify processing
is prohibitively slow across 2.6k cells -- this is documented in test/Makefile,
which strips ALL specify blocks for the zero-delay functional GL suite.

This script makes a *different* variant for timing simulation: it keeps the
IOPATH/SETUP arcs (so $sdf_annotate has annotation targets and cell delays are
real) and removes only the timing-check statements plus their delayed_*
plumbing.

Output: data/sdfsim/sg13g2_stdcell_sdf.v
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common as C  # noqa: E402

PDK_VERILOG = (
    C.PDK_HOST
    + "/ciel/ihp-sg13g2/versions/"
    + C.CIEL_PDK_REV
    + "/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/sg13g2_stdcell.v"
)

CHECK_START = re.compile(
    r"^\s*\$(?:setuphold|setup|hold|recrem|width|period|skew2|skew|nochange)\b"
)


def patch(text):
    out = []
    drop_next_semi = False
    for chunk in re.split(r"(;)", text):
        if drop_next_semi:
            if chunk == ";":
                drop_next_semi = False
            continue
        if CHECK_START.match(chunk):
            drop_next_semi = True
            continue
        out.append(chunk)
    text = "".join(out)
    # delayed_* plumbing: rename to the real ports so the DFF primitives see
    # real signals (same trick as the zero-delay GL patch in test/Makefile).
    # The `reg notifier` / `wire delayed_*` declarations are kept: notifier is
    # an argument of the ihp_dff_* primitives.
    text = re.sub(r"\bdelayed_([A-Za-z_][A-Za-z_0-9]*)", r"\1", text)
    return text


def main():
    src = open(PDK_VERILOG).read()
    dst_dir = os.path.join(C.DATA, "sdfsim")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "sg13g2_stdcell_sdf.v")
    open(dst, "w").write(patch(src))
    n_checks = len(re.findall(
        r"\$(?:setuphold|setup|hold|recrem|width|period|skew2|skew|nochange)\b",
        src))
    print(f"wrote {dst} (removed {n_checks} timing-check statements, "
          f"kept IOPATH arcs)")


if __name__ == "__main__":
    main()
