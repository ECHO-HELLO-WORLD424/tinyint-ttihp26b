#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Produce a simulation copy of the post-route netlist with every escaped
identifier renamed to underscore form (see sdfnames.py), so SDF (INSTANCE)
strings -- sanitized the same way by filter_sdf.py -- bind in Icarus.

Usage: rename_netlist.py <nl.v> <netlist_sim.v>
"""

import sys

import sdfnames


def main():
    src, dst = sys.argv[1], sys.argv[2]
    text = open(src).read()
    sdfnames.check_collisions(text)
    out = sdfnames.sanitize_text(text)
    n = sum(1 for _ in sdfnames.ESC_RE.finditer(text))
    open(dst, 'w').write(out)
    print("rename_netlist: renamed %d escaped identifiers -> %s" % (n, dst))


if __name__ == "__main__":
    main()
