# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Shared escaped-identifier sanitization for SDF timing simulation.

The post-route netlist keeps Yosys's flattened escaped instance names
(e.g. \\u_dut.g_seg[0].g_fa[0].u_fa.u_a1 ). Icarus's SDF binder treats the
dots in an SDF (INSTANCE ...) field as hierarchy separators, so annotation
fails with "Cannot find u_dut in scope tb_sdfsim.dut". The fix is to rename
every escaped identifier to underscore form ( '.' -> '_', '[' -> '_',
']' -> '_' ) in BOTH a simulation copy of the netlist and the (INSTANCE)
fields of the filtered SDF, so the two agree under plain name lookup.

Renaming must be applied to every escaped identifier (wires and instances)
to keep the netlist self-consistent. A collision check rejects any pair of
distinct original identifiers that would map to the same canonical name.
"""

import re

# An escaped identifier: backslash + run of non-space characters.
# In these netlists/SDFs identifiers are always delimited by whitespace.
ESC_RE = re.compile(r'\\(\S+)')

_CHARS = {'.': '_', '[': '_', ']': '_'}


def canon(ident):
    """Canonical (post-sanitize) name of an escaped identifier body."""
    return ident.translate(str.maketrans(_CHARS))


def sanitize_text(text):
    """Rewrite every escaped identifier in a Verilog source to canon form."""
    return ESC_RE.sub(lambda m: '\\' + canon(m.group(1)), text)


def check_collisions(text):
    """Raise if two distinct escaped identifiers collapse to one name."""
    seen = {}
    for m in ESC_RE.finditer(text):
        orig, new = m.group(1), canon(m.group(1))
        if seen.setdefault(new, orig) != orig:
            raise SystemExit(
                "identifier collision: \\%s and \\%s both become %s"
                % (orig, seen[new], new))
