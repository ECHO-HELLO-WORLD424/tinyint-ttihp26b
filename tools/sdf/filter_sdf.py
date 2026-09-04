#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Filter a corner SDF for Icarus full-chip annotation.

Keeps per-cell IOPATH delay entries; drops the top-level INTERCONNECT-only
CELL block (Icarus's interconnect annotator does not resolve this design's
SDF interconnect section) and all TIMINGCHECK blocks (no timing checks are
simulated; hold is validated by STA signoff instead).

The resulting annotation carries cell IOPATH delays only; the wire-delay
scope is recorded in data/sdf_path_check.csv.

Usage: filter_sdf.py <corner.sdf> <corner.iopath.sdf>
"""

import sys


def tokenize(text):
    toks = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            j = i + 1
            while j < n and text[j] != c:
                j += 1
            toks.append(('str', text[i:j + 1]))
            i = j + 1
        elif c == '(':
            toks.append(('open', '('))
            i += 1
        elif c == ')':
            toks.append(('close', ')'))
            i += 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"\'':
                j += 1
            toks.append(('atom', text[i:j]))
            i = j
    return toks


def parse(toks, pos=0):
    assert toks[pos][0] == 'open', toks[pos]
    pos += 1
    head = None
    if pos < len(toks) and toks[pos][0] in ('atom', 'str'):
        head = toks[pos][1]
        pos += 1
    children = []
    while toks[pos][0] != 'close':
        if toks[pos][0] == 'open':
            node, pos = parse(toks, pos)
            children.append(node)
        else:
            children.append(('atom', toks[pos][1]))
            pos += 1
    return (head, children), pos + 1


def emit(node):
    head, children = node
    parts = ['(' + (head or '')]
    for ch in children:
        if ch[0] == 'atom':
            parts.append(ch[1])
        else:
            parts.append(emit(ch))
    return ' '.join(parts) + ')'


root, _ = parse(tokenize(open(sys.argv[1]).read()))
assert root[0] == 'DELAYFILE', root[0]

kept_cells = 0
dropped = 0
new_children = []
for node in root[1]:
    if node[0] == 'CELL':
        instance = None
        for ch in node[1]:
            if ch[0] == 'INSTANCE':
                instance = ' '.join(x[1] for x in ch[1] if x[0] == 'atom')
        if not instance:
            dropped += 1  # top-level interconnect-only block
            continue
        inner = [ch for ch in node[1] if ch[0] != 'TIMINGCHECK']
        if len(inner) != len(node[1]):
            dropped += 1
        new_children.append(('CELL', inner))
        kept_cells += 1
    else:
        new_children.append(node)

root = ('DELAYFILE', new_children)
open(sys.argv[2], 'w').write(emit(root) + '\n')
print(f"filter_sdf: kept {kept_cells} cell blocks, dropped {dropped} sections"
      f" -> {sys.argv[2]}")
