#!/usr/bin/env python3
# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Standalone validation of the Python boundary-monitor mirrors.

Replays the trace produced by p4_monitor_trace_tb.v (one line per accepted
command: `C <mode>` or `M <written> <extbit> <boundary>`) through the exact
BoundaryMonitor classes used by the cocotb suites, asserting that the mirror
boundary equals the RTL effective boundary after every accepted MAC.

Run (after vvp p4_monitor_trace.vvp):
    python3 p4_monitor_replay.py [p4_monitor_trace.log]
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_class(filename, class_name):
    spec = importlib.util.spec_from_file_location(
        os.path.splitext(filename)[0], os.path.join(HERE, filename)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def replay(path, mirrors):
    monitors = [cls(0) for cls in mirrors]
    macs = written_count = skipped = 0
    windows = boundary_8_steps = 0
    last_boundary = None
    transitions = set()
    with open(path) as fh:
        for lineno, line in enumerate(fh, 1):
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "C":
                mode = int(parts[1])
                monitors = [cls(mode) for cls in mirrors]
                continue
            assert parts[0] == "M", f"unexpected trace token {parts!r}"
            written = int(parts[1]) != 0
            addend = int(parts[2]) << 19
            rtl_boundary = int(parts[3])
            for monitor in monitors:
                monitor.on_mac(written, addend)
                if monitor.effective != rtl_boundary:
                    print(f"FAIL {os.path.basename(path)} line {lineno}: "
                          f"mirror effective {monitor.effective} != RTL "
                          f"{rtl_boundary}")
                    return 1
            macs += 1
            if written:
                written_count += 1
            else:
                skipped += 1
            if monitors[0].window_count == 0:
                windows += 1
            if rtl_boundary == 0b01:
                boundary_8_steps += 1
            if last_boundary is not None and rtl_boundary != last_boundary:
                transitions.add((last_boundary, rtl_boundary))
            last_boundary = rtl_boundary
    print(f"PASS {os.path.basename(path)}: {macs} accepted MACs "
          f"({written_count} written / {skipped} skipped), {windows} "
          f"windows, {boundary_8_steps} steps at boundary 8, transitions "
          f"{sorted(transitions)}, both mirror copies match RTL at every "
          f"step")
    return 0


def main(argv):
    path = argv[1] if len(argv) > 1 else os.path.join(
        HERE, "p4_monitor_trace.log")
    if not os.path.exists(path):
        print(f"trace {path} not found; run p4_monitor_trace_tb.v first")
        return 2
    mirrors = [
        load_class("test_core_multistage.py", "BoundaryMonitor"),
        load_class("test_core_multistage_gate.py", "BoundaryMonitor"),
    ]
    return replay(path, mirrors)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
