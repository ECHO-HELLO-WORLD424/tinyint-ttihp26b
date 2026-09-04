#!/usr/bin/env python3
# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Filter the gate-level netlist for GL simulation.

The ring-oscillator canary loops are asynchronous free-running structures:
in zero-delay functional GL simulation they would either hang the simulator
(combinational loop) or not model anything meaningful. This script removes
the canary loop cells (everything instantiated inside the u_ro_gen/u_ro_mat
canaries except their edge counters, which are ordinary flip-flops that
simply never clock while the loops are stalled) and leaves the rest of the
design untouched. The cocotb GL tests assert the canary counters stay at
zero, which validates the readout path for those bytes.
"""
import re
import sys

src_path, dst_path = sys.argv[1], sys.argv[2]

# Instance-name pattern: cells whose instance name lives in a canary scope,
# excluding flip-flops (the RO edge counters are anonymous dfrbpq cells).
cell_re = re.compile(r"sg13g2_[a-z0-9_]+\s+\\?u_ro_(gen|mat)\.")
ff_re = re.compile(r"sg13g2_dfr")

out = []
skip = False
removed = 0
for line in open(src_path):
    if cell_re.search(line) and not ff_re.search(line):
        skip = True
        removed += 1
    if not skip:
        out.append(line)
    elif re.search(r"\);\s*$", line):
        skip = False

open(dst_path, "w").write("\n".join(out))
print(f"strip_ro_cells: removed {removed} canary cells -> {dst_path}")
