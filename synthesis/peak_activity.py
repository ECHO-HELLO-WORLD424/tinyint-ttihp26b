#!/usr/bin/env python3
"""Per-cycle activity extraction and VCD window slicing for peak power.

This script reads a gate-level VCD produced by ``test/power_activity_tb.v`` and
computes, for every fixed clock-aligned window, the number of state transitions
and a capacitance-weighted switching-energy proxy. The windows with the highest
activity are then emitted as self-contained VCD slices so that a stock OpenSTA
``read_vcd`` (which has no time-window option) can measure the exact power of
each candidate cycle.

The energy proxy uses the nominal extracted SPEF capacitance of each net with
``E = 0.5 * C * V^2 * flips`` at V = 1.2 V. It is only used to rank windows; the
reported peak power comes from OpenSTA on each slice.

The routed netlist is hierarchical, so the VCD reuses identifier codes across
scopes for aliases of the same net. The parser keeps the first declaration of
each code (normally the parent net) and copies the original header verbatim into
each slice so that ``read_vcd -scope power_activity_tb/user_project`` resolves
identifiers exactly as it does for the full trace.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

VOLTAGE = 1.2
# 0.5 * (pF -> F) * V^2 expressed in fJ: 0.5 * 1e-12 * 1.44 * 1e15 = 720 fJ/pF/flip
FEMTOJOULE_PER_PF_FLIP = 0.5 * 1e-12 * VOLTAGE * VOLTAGE * 1e15

NAME_MAP_RE = re.compile(r"^\*(\d+)\s+(\S+)\s*$")
D_NET_RE = re.compile(r"^\*D_NET\s+\*(\d+)\s+([0-9.eE+-]+)\s*$")


def parse_spef_caps(path):
    """Return {net_name: total_capacitance_pF} from a SPEF NAME_MAP + D_NET."""
    names = {}
    caps_by_id = {}
    with open(path, "r", encoding="ascii", errors="replace") as stream:
        for line in stream:
            line = line.rstrip("\n")
            match = NAME_MAP_RE.match(line)
            if match:
                names[match.group(1)] = match.group(2)
                continue
            match = D_NET_RE.match(line)
            if match:
                caps_by_id[match.group(1)] = float(match.group(2))
    caps = {}
    for net_id, cap in caps_by_id.items():
        name = names.get(net_id)
        if name is not None:
            caps[name] = cap
    return caps


def parse_var_line(line):
    """Parse a VCD ``$var`` line.

    Returns (code, width, name, range_text) or None when the line is not a
    well-formed variable declaration.
    """
    fields = line.split()
    if len(fields) < 5 or fields[0] != "$var" or fields[-1] != "$end":
        return None
    width_text = fields[2]
    code = fields[3]
    reference = fields[4:-1]
    if not reference:
        return None
    name = reference[0]
    range_text = " ".join(reference[1:])
    try:
        width = int(width_text)
    except ValueError:
        return None
    return code, width, name, range_text


def parse_scope_line(line):
    fields = line.split()
    if not fields:
        return None
    if fields[0] == "$scope":
        if len(fields) >= 3:
            return ("push", fields[2])
        return None
    if fields[0] == "$upscope":
        return ("pop", None)
    return None


def scan_declarations(stream):
    """Consume the VCD header.

    Returns a dict with:
      codes      set of identifier codes declared inside user_project
      width      code -> bit width (first declaration wins)
      names      code -> list of names (first declaration first)
      header     verbatim header lines through ``$enddefinitions $end``
    """
    scope = []
    codes = set()
    width = {}
    names = {}
    header = []
    for line in stream:
        stripped = line.strip()
        header.append(line.rstrip("\n"))
        if not stripped:
            continue
        if stripped.startswith("$var"):
            if "user_project" in scope:
                parsed = parse_var_line(stripped)
                if parsed is not None:
                    code, bits, name, _ = parsed
                    codes.add(code)
                    if code not in width:
                        width[code] = bits
                    names.setdefault(code, []).append(name)
            continue
        scope_event = parse_scope_line(stripped)
        if scope_event is not None:
            kind, value = scope_event
            if kind == "push":
                scope.append(value)
            elif scope:
                scope.pop()
            continue
        if stripped.startswith("$enddefinitions"):
            break
    return {
        "codes": codes,
        "width": width,
        "names": names,
        "header": header,
    }


def classify_change(line):
    """Return (code, value_kind, value) for a VCD value-change line."""
    first = line[0]
    if first == "#":
        return None
    if first in "bB":
        body = line[1:]
        space = body.find(" ")
        if space < 0:
            return None
        bits = body[:space]
        code = body[space + 1:].strip()
        if not code:
            return None
        return code, "vector", bits
    if first in "01xXzZ":
        code = line[1:].strip()
        if not code:
            return None
        return code, "scalar", first
    return None


def flip_count(previous, kind, value):
    if previous is None:
        return 0
    if kind == "scalar":
        if previous in "01" and value in "01" and previous != value:
            return 1
        return 0
    if len(previous) != len(value):
        return 0
    flips = 0
    for old_bit, new_bit in zip(previous, value):
        if old_bit in "01" and new_bit in "01" and old_bit != new_bit:
            flips += 1
    return flips


def code_capacitance(decls, caps):
    """Map code -> capacitance using the first alias found in the SPEF."""
    result = {}
    for code, alias_names in decls["names"].items():
        best = 0.0
        for name in alias_names:
            if name in caps:
                best = caps[name]
                break
        result[code] = best
    return result


def measure_activity(path, caps, window_ps, begin_ps):
    """Return (declarations, per_window).

    per_window maps window index to [flips, energy_fJ].
    """
    with open(path, "r", encoding="ascii", errors="replace") as stream:
        decls = scan_declarations(stream)
        codes = decls["codes"]
        code_cap = code_capacitance(decls, caps)
        previous = {}
        per_window = {}
        time = 0
        for line in stream:
            line = line.rstrip("\n")
            if not line:
                continue
            if line[0] == "#":
                try:
                    time = int(line[1:])
                except ValueError:
                    continue
                continue
            change = classify_change(line)
            if change is None:
                continue
            code, kind, value = change
            if code not in codes:
                continue
            flips = flip_count(previous.get(code), kind, value)
            previous[code] = value
            if flips == 0:
                continue
            if time < begin_ps:
                continue
            window = (time - begin_ps) // window_ps
            entry = per_window.get(window)
            if entry is None:
                entry = [0, 0.0]
                per_window[window] = entry
            entry[0] += flips
            entry[1] += FEMTOJOULE_PER_PF_FLIP * code_cap.get(code, 0.0) * flips
    return decls, per_window


def format_initial(code, bit_width, value):
    if value is None:
        if bit_width == 1:
            return "x{}".format(code)
        return "b{} {}".format("x" * bit_width, code)
    if bit_width == 1:
        return "{}{}".format(value, code)
    bits = value
    if len(bits) != bit_width and "x" not in bits and "z" not in bits:
        bits = bits.rjust(bit_width, "0")
    return "b{} {}".format(bits, code)


def write_slice(path, decls, snapshots, changes, begin_ps, end_ps):
    """Write a self-contained single-window VCD slice."""
    width = decls["width"]
    with open(path, "w", encoding="ascii") as out:
        for line in decls["header"]:
            out.write(line + "\n")
        out.write("#{}\n".format(begin_ps))
        for code in sorted(decls["codes"]):
            out.write(format_initial(code, width[code], snapshots.get(code)))
            out.write("\n")
        current_time = None
        for timestamp, raw in changes:
            if timestamp != current_time:
                out.write("#{}\n".format(timestamp))
                current_time = timestamp
            out.write(raw + "\n")
        out.write("#{}\n".format(end_ps))


def slice_candidates(path, decls, candidates, outdir, prefix, window_ps):
    """Second pass: snapshot state and collect changes for candidate windows."""
    codes = decls["codes"]
    candidate_set = {c["window"] for c in candidates}
    buffers = {window: [] for window in candidate_set}
    snapshots = {window: None for window in candidate_set}
    ordered = sorted(candidate_set)
    next_index = 0
    previous = {}
    time = 0

    with open(path, "r", encoding="ascii", errors="replace") as stream:
        _ = scan_declarations(stream)
        for line in stream:
            line = line.rstrip("\n")
            if not line:
                continue
            if line[0] == "#":
                try:
                    time = int(line[1:])
                except ValueError:
                    continue
                while next_index < len(ordered):
                    window = ordered[next_index]
                    if time < window * window_ps:
                        break
                    snapshots[window] = dict(previous)
                    next_index += 1
                continue
            change = classify_change(line)
            if change is None:
                continue
            code, kind, value = change
            if code not in codes:
                continue
            previous[code] = value
            window = time // window_ps
            if window in buffers:
                buffers[window].append((time, line))

    for window in ordered:
        if snapshots[window] is None:
            snapshots[window] = dict(previous)

    slice_paths = {}
    for candidate in candidates:
        window = candidate["window"]
        out_path = os.path.join(
            outdir, "{}_win{:06d}.vcd".format(prefix, window)
        )
        write_slice(
            out_path, decls, snapshots.get(window, {}),
            buffers.get(window, []), candidate["begin_ps"], candidate["end_ps"],
        )
        slice_paths[window] = out_path
    return slice_paths


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vcd", required=True)
    parser.add_argument("--spef", default=None)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--window-ps", type=int, default=20000)
    parser.add_argument("--begin-ps", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=32)
    args = parser.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)

    caps = parse_spef_caps(args.spef) if args.spef else {}

    decls, per_window = measure_activity(
        args.vcd, caps, args.window_ps, args.begin_ps
    )
    if not decls["codes"]:
        raise SystemExit("no user_project variables found in {}".format(args.vcd))

    activity_path = os.path.join(
        args.outdir, "{}.activity.csv".format(args.prefix)
    )
    with open(activity_path, "w", encoding="ascii") as out:
        out.write("window,begin_ps,end_ps,flips,energy_fJ\n")
        for window in sorted(per_window):
            flips, energy = per_window[window]
            out.write(
                "{},{},{},{},{:.6f}\n".format(
                    window, args.begin_ps + window * args.window_ps,
                    args.begin_ps + (window + 1) * args.window_ps,
                    flips, energy,
                )
            )

    ranked = sorted(
        per_window.items(),
        key=lambda item: (item[1][1], item[1][0]),
        reverse=True,
    )[: args.top_k]

    candidates = []
    for rank, (window, (flips, energy)) in enumerate(ranked, start=1):
        candidates.append(
            {
                "rank": rank,
                "window": window,
                "begin_ps": args.begin_ps + window * args.window_ps,
                "end_ps": args.begin_ps + (window + 1) * args.window_ps,
                "flips": flips,
                "energy_fJ": energy,
            }
        )

    slice_paths = slice_candidates(
        args.vcd, decls, candidates, args.outdir, args.prefix, args.window_ps
    )

    candidates_path = os.path.join(
        args.outdir, "{}.candidates.csv".format(args.prefix)
    )
    with open(candidates_path, "w", encoding="ascii") as out:
        out.write("rank,window,begin_ps,end_ps,flips,energy_fJ,slice\n")
        for candidate in candidates:
            out.write(
                "{rank},{window},{begin_ps},{end_ps},{flips},{energy:.6f},{slice}\n".format(
                    rank=candidate["rank"], window=candidate["window"],
                    begin_ps=candidate["begin_ps"], end_ps=candidate["end_ps"],
                    flips=candidate["flips"], energy=candidate["energy_fJ"],
                    slice=os.path.basename(slice_paths[candidate["window"]]),
                )
            )

    print(
        "{}: {} DUT codes, {} active windows, {} candidates".format(
            args.prefix, len(decls["codes"]), len(per_window), len(candidates)
        )
    )
    print("activity: {}".format(activity_path))
    print("candidates: {}".format(candidates_path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
