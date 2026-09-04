#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Reduce a corner SDF to an Icarus-annotatable IOPATH-only file.

Transformations (scope recorded in data/sdf_path_check.csv):
  1. Drop the top-level INTERCONNECT-only CELL block (Icarus's interconnect
     annotator crashes on this design's SDF).
  2. Drop all TIMINGCHECK blocks (no timing checks are simulated; hold is
     validated by STA signoff instead).
  3. Rewrite a::b MTM tokens as a:a:b (Icarus cannot parse empty MTM
     fields; all three values are equal in these SDFs anyway).
  4. Replace empty delay triples "()" with 0.000:0.000:0.000 (async-reset
     Q rise arcs carry no annotated delay).
  5. Strip (COND <expr> (IOPATH ...)) wrappers inside (ABSOLUTE ...):
     keep the unconditional IOPATH when one exists for the same port pair,
     else unwrap the first conditional variant and drop duplicate
     conditional variants of the same pair. Conditional arc refinement is
     thereby lost; acceptable for first-order capture-path timing.

Usage: filter_sdf.py <corner.sdf> <corner.iopath.sdf>

The (INSTANCE ...) fields are additionally renamed to underscore form with
sdfnames.canon(), matching the simulation netlist copy produced by
rename_netlist.py (Icarus's SDF binder treats dots as hierarchy
separators, which cannot bind to the flattened escaped instance names).
"""

import sys

import sdfnames


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
            children.append((toks[pos][0], toks[pos][1]))
            pos += 1
    return (head, children), pos + 1


def emit(node):
    head, children = node
    parts = ['(' + (head or '')]
    for ch in children:
        if ch[0] in ('atom', 'str'):
            parts.append(ch[1])
        else:
            parts.append(emit(ch))
    return ' '.join(parts) + ')'


def fix_tokens(node):
    """Rewrite a::b tokens and empty () triples everywhere in the tree."""
    head, children = node
    if head is None and not children:
        return ('0.000:0.000:0.000', [])
    fixed = []
    for ch in children:
        if ch[0] == 'atom':
            v = ch[1]
            if '::' in v:
                a, b = v.split('::', 1)
                fixed.append(('atom', a + ':' + a + ':' + b))
            else:
                fixed.append(ch)
        elif ch[0] == 'str':
            v = ch[1]
            if '::' in v:
                inner = v.strip('"\'')
                a, b = inner.split('::', 1)
                fixed.append(('str', '"' + a + ':' + a + ':' + b + '"'))
            else:
                fixed.append(ch)
        else:
            fixed.append(fix_tokens(ch))
    return (head, fixed)


def iopath_key(node):
    return (node[1][0][1], node[1][1][1])


def fix_absolute(node):
    """Inside (ABSOLUTE ...): drop COND wrappers per the rules."""
    head, children = node
    plain = []
    plain_keys = set()
    unwrapped = []
    unwrapped_keys = set()
    for ch in children:
        if ch[0] == 'IOPATH':
            k = iopath_key(ch)
            if k not in plain_keys:
                plain.append(ch)
                plain_keys.add(k)
        elif ch[0] == 'COND':
            inner = next((c for c in ch[1] if c[0] == 'IOPATH'), None)
            if inner is None:
                continue
            k = iopath_key(inner)
            if k in plain_keys or k in unwrapped_keys:
                continue  # duplicate conditional variant: drop
            unwrapped.append(inner)
            unwrapped_keys.add(k)
        else:
            plain.append(ch)  # keep anything else as-is
    return ('ABSOLUTE', plain + unwrapped), len(unwrapped)


stats = {"cells": 0, "sections": 0, "unwrapped": 0, "renamed": 0}

root, _ = parse(tokenize(open(sys.argv[1]).read()))
assert root[0] == 'DELAYFILE', root[0]

new_children = []
for node in root[1]:
    if node[0] == 'CELL':
        instance = None
        for ch in node[1]:
            if ch[0] == 'INSTANCE':
                instance = ' '.join(x[1] for x in ch[1] if x[0] == 'atom')
        if not instance:
            stats["sections"] += 1  # top-level interconnect-only block
            continue
        inst_renamed = sdfnames.canon(instance)
        if inst_renamed != instance:
            stats["renamed"] += 1
        inner = []
        for ch in node[1]:
            if ch[0] == 'INSTANCE':
                inner.append(('INSTANCE', [('atom', inst_renamed)]))
            elif ch[0] == 'TIMINGCHECK':
                stats["sections"] += 1
            elif ch[0] == 'DELAY':
                dhead, dchildren = ch
                new_delay = []
                for d in dchildren:
                    if d[0] == 'ABSOLUTE':
                        fixed, n_unwrap = fix_absolute(d)
                        stats["unwrapped"] += n_unwrap
                        new_delay.append(fixed)
                    else:
                        new_delay.append(d)
                inner.append(('DELAY', new_delay))
            else:
                inner.append(ch)
        new_children.append(('CELL', inner))
        stats["cells"] += 1
    else:
        new_children.append(node)

root = fix_tokens(('DELAYFILE', new_children))
open(sys.argv[2], 'w').write(emit(root) + '\n')
print("filter_sdf: kept {cells} cells, dropped {sections} sections, "
      "unwrapped {unwrapped} conditional IOPATHs, renamed {renamed} "
      "instances -> {out}".format(out=sys.argv[2], **stats))
