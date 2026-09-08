#!/usr/bin/env python3
# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Interactive cocotb emulator for the tt_um_echoworld424_tpv test chip.

Examples
--------
    # interactive pin-level session on the RTL model
    python3 tools/chip_emulate.py repl

    # same, but on the post-route netlist with the slow-corner SDF
    python3 tools/chip_emulate.py repl --backend sdf --corner slow

    # one measurement, decoded
    python3 tools/chip_emulate.py run hello --backend sdf --corner typ --period 14

    # first-failure clock period at every PVT corner
    python3 tools/chip_emulate.py pvtsweep

    # regression fixture (RTL and SDF)
    python3 tools/chip_emulate.py selftest --backend sdf --corner slow

Simulation commands run inside the repository devcontainer by default (Icarus
12.0 + cocotb 2.0.1, the versions used by test/Makefile); ``--toolchain local``
uses the current interpreter's cocotb and iverilog instead.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from typing import List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
CONTAINER_REPO = "/workspaces/tinyint-ttihp26b"
CONTAINER_IMAGE_PREFIX = "vsc-tinyint-ttihp26b-"
WAVES_DIR = os.path.join(REPO, "runs", "emulator", "waves")

if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)


# ------------------------------------------------------------- toolchain -----


def _in_container() -> bool:
    return os.path.isdir(CONTAINER_REPO)


def _devcontainer() -> Optional[str]:
    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}} {{.Image}}"],
            capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].startswith(CONTAINER_IMAGE_PREFIX):
            return parts[0]
    return None


def _to_container_path(arg: str) -> str:
    if arg.startswith(REPO + os.sep):
        return CONTAINER_REPO + arg[len(REPO):]
    return arg


def _reexec_in_devcontainer(argv: List[str]) -> None:
    """Replace this process with the same command inside the devcontainer."""
    name = _devcontainer()
    if name is None:
        return
    # common options live on the subparser, so the flag goes after the command
    args = list(argv)
    translated = [_to_container_path(a) for a in args]
    if args:
        translated = [translated[0], "--toolchain", "container"] + translated[1:]
    else:
        translated = ["--toolchain", "container"]
    inner = ("source /ttsetup/venv/bin/activate && cd %s && "
             "exec python3 tools/chip_emulate.py %s"
             % (CONTAINER_REPO, " ".join(shlex.quote(a) for a in translated)))
    cmd = ["docker", "exec", "-i"]
    if sys.stdin.isatty():
        cmd.append("-t")
    cmd += [name, "bash", "-lc", inner]
    os.execvp("docker", cmd)


def _resolve_toolchain(mode: str) -> str:
    if mode == "local":
        return "local"
    if _in_container():
        return "container"
    if mode == "container":
        raise SystemExit("--toolchain container requires running inside the "
                         "devcontainer (%s)" % CONTAINER_REPO)
    if mode in ("auto", "devcontainer"):
        if _devcontainer() is not None:
            return "devcontainer"
        if mode == "devcontainer":
            raise SystemExit("devcontainer is not running; start it or use "
                             "--toolchain local")
        print("[emulator] devcontainer not running: using local cocotb/iverilog "
              "(versions may differ from the audited toolchain)", file=sys.stderr)
    return "local"


# ------------------------------------------------------------- commands ------


def _corner(args):
    from emulator.pvt import get_corner
    if args.backend == "rtl":
        return None
    return get_corner(args.corner)


def _waves_path(args, tag: str) -> Optional[str]:
    if not args.waves:
        return None
    os.makedirs(WAVES_DIR, exist_ok=True)
    return os.path.join(WAVES_DIR, "%s-%s.fst"
                        % (tag, time.strftime("%Y%m%d-%H%M%S")))


def _results_dir(args) -> str:
    if args.results_dir:
        return os.path.abspath(args.results_dir)
    return os.path.join(REPO, "runs", "emulator", "results",
                        time.strftime("%Y%m%d-%H%M%S"))


def cmd_corners(args) -> int:
    from emulator import artifacts
    report = artifacts.availability()
    print("%-24s %-14s %-6s %s" % ("corner", "supply/temp", "SDFs", "artifacts"))
    for name, info in report.items():
        pvt = info["pvt"]
        sdf_desc = ", ".join(
            "%s%s" % ("filtered" if filt else "raw", " run-%s" % run if run else "")
            for _path, filt, run in info["sdfs"]) or "-"
        print("%-24s %-14s %-6d %s" % (
            name, pvt.label, len(info["sdfs"]), sdf_desc))
    print("\nnetlist candidates: %d   stdcell lib: %s" % (
        report[next(iter(report))]["netlists"],
        os.path.relpath(report[next(iter(report))]["lib"], REPO)
        if report[next(iter(report))]["lib"] else "MISSING"))
    return 0


def cmd_prepare(args) -> int:
    from emulator import artifacts
    return artifacts.main(args.corners)


def cmd_repl(args) -> int:
    from emulator import runner
    script = os.path.abspath(args.script) if args.script else None
    if script and not os.path.isfile(script):
        raise SystemExit("script not found: %s" % script)
    return runner.run(
        backend=args.backend, scenario="repl", corner=_corner(args),
        period_ns=args.period, duty=args.duty, script=script,
        waves=_waves_path(args, "repl"), sdf=args.sdf, netlist=args.netlist,
        rebuild=args.rebuild, results_dir=_results_dir(args),
        test_module=args.module, verbose=args.verbose)


def cmd_run(args) -> int:
    from emulator import runner
    return runner.run(
        backend=args.backend, scenario=args.scenario, corner=_corner(args),
        period_ns=args.period, duty=args.duty, ops=args.ops,
        waves=_waves_path(args, args.scenario), sdf=args.sdf,
        netlist=args.netlist, rebuild=args.rebuild,
        results_dir=_results_dir(args), test_module=args.module,
        verbose=args.verbose, extra_plusargs=_scenario_args(args))


def _scenario_args(args) -> dict:
    out = {}
    for key in ("segs", "pat", "cansel", "winsel", "force_err", "force_can"):
        value = getattr(args, key, None)
        if value is not None:
            out[key] = value
    return out


def cmd_selftest(args) -> int:
    from emulator import runner
    return runner.run(
        backend=args.backend, scenario="selftest", corner=_corner(args),
        period_ns=args.period, duty=args.duty, waves=_waves_path(args, "selftest"),
        sdf=args.sdf, netlist=args.netlist, rebuild=args.rebuild,
        results_dir=_results_dir(args), test_module=args.module,
        verbose=args.verbose)


def cmd_pvtsweep(args) -> int:
    import json

    from emulator import runner
    from emulator.pvt import CORNERS, corner_names, get_corner

    if args.backend == "rtl":
        print("[emulator] RTL is zero-delay: a PVT sweep is only meaningful "
              "with --backend sdf", file=sys.stderr)
        return runner.run(backend="rtl", scenario="pvtsweep", corner=None,
                          period_ns=args.period, duty=args.duty, ops=args.ops,
                          results_dir=_results_dir(args),
                          extra_plusargs=_scenario_args(args))

    names = corner_names() if args.corners in (None, ["all"]) else args.corners
    if args.sdf and len(names) > 1:
        raise SystemExit("--sdf applies to a single corner; use --corners <one>")
    out_dir = _results_dir(args)
    os.makedirs(out_dir, exist_ok=True)
    summary = []
    rc = 0
    for name in names:
        corner = get_corner(name)
        out_json = os.path.join(out_dir, "pvtsweep-%s.json" % corner.name)
        extra = _scenario_args(args)
        extra["out"] = out_json
        for key, value in (("pmin", args.pmin), ("pmax", args.pmax),
                           ("steps", args.steps), ("tol", args.tol)):
            if value is not None:
                extra[key] = value
        print("\n" + "#" * 78)
        print("# PVT corner %s" % corner)
        print("#" * 78)
        rc |= runner.run(
            backend="sdf", scenario="pvtsweep", corner=corner,
            period_ns=args.period, duty=args.duty, ops=args.ops,
            waves=_waves_path(args, "pvtsweep-%s" % corner.name),
            sdf=args.sdf, netlist=args.netlist, rebuild=args.rebuild,
            results_dir=out_dir, extra_plusargs=extra)
        try:
            with open(out_json) as fh:
                summary.append(json.load(fh))
        except (OSError, ValueError):
            pass

    if summary:
        print("\n" + "=" * 78)
        print(" PVT summary: DUT first-failure boundary (config 0x%s)"
              % format(summary[0].get("config", {}).get("word", 0) & 0xFFFF,
                       "04X"))
        print("=" * 78)
        print("%-24s %-14s %12s %12s %12s" % (
            "corner", "supply/temp", "fail<ns", "pass>ns", "f_fail_MHz"))
        for entry in summary:
            corner_name = entry.get("corner") or "?"
            pvt = CORNERS.get(corner_name)
            fail = entry.get("boundary_fail_period_ns")
            passing = entry.get("boundary_pass_period_ns")
            print("%-24s %-14s %12s %12s %12s" % (
                corner_name, pvt.label if pvt else "?",
                ("%.4f" % fail) if fail else "n/a",
                ("%.4f" % passing) if passing else "n/a",
                ("%.3f" % (1e3 / passing)) if passing else "n/a"))
        merged = os.path.join(out_dir, "pvtsweep-summary.json")
        with open(merged, "w") as fh:
            json.dump({"corners": summary}, fh, indent=1)
        print("\nwrote %s" % merged)
    return rc


# ------------------------------------------------------------- argparse ------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--toolchain", default="auto",
                        choices=["auto", "devcontainer", "container", "local"],
                        help="where to run cocotb/iverilog (default: devcontainer "
                             "when available, else local)")
    common.add_argument("--backend", default="rtl", choices=["rtl", "sdf"],
                        help="rtl = zero-delay functional; sdf = post-route "
                             "netlist + corner SDF (PVT-dependent)")
    common.add_argument("--corner", default=None,
                        help="PVT corner (typ|slow|fast or a full corner name)")
    common.add_argument("--period", type=float, default=100.0,
                        help="clock period in ns (default 100 -> 10 MHz)")
    common.add_argument("--duty", type=float, default=0.5,
                        help="clock duty cycle; high time is the capture aperture")
    common.add_argument("--ops", type=int, default=None,
                        help="measured operations (frames) per point")
    common.add_argument("--waves", action="store_true",
                        help="dump an FST waveform under runs/emulator/waves/")
    common.add_argument("--rebuild", action="store_true",
                        help="force recompilation")
    common.add_argument("--results-dir", default=None,
                        help="directory for results.xml and sweep JSON")
    common.add_argument("--sdf", default=None,
                        help="use this SDF instead of the corner's artifact")
    common.add_argument("--netlist", default=None,
                        help="use this post-route netlist instead of the "
                             "discovered one")
    common.add_argument("--verbose", action="store_true")
    common.add_argument("--module", default="emulator.session",
                        help="cocotb test module to run (default: the built-in "
                             "scenario dispatcher; e.g. emulator.example_custom_test)")

    parser = argparse.ArgumentParser(
        prog="chip_emulate.py",
        description="Interactive cocotb emulator for tt_um_echoworld424_tpv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("corners", parents=[common],
                       help="list PVT corners and available artifacts")
    p.set_defaults(func=cmd_corners)

    p = sub.add_parser("prepare", parents=[common],
                       help="filter/rename the netlist and corner SDFs into "
                            "runs/emulator/sdf/")
    p.add_argument("corners", nargs="*", help="corner names (default: all)")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("repl", parents=[common],
                       help="interactive pin-level session")
    p.add_argument("--script", default=None,
                   help="run commands from a file instead of reading stdin")
    p.set_defaults(func=cmd_repl)

    p = sub.add_parser("run", parents=[common], help="run one scenario")
    p.add_argument("scenario", nargs="?", default="hello",
                   choices=["hello", "pins", "patterns", "dft", "pvtsweep",
                            "selftest"],
                   help="built-in scenario (ignored when --module is used)")
    p.add_argument("--segs", default=None, help="segment delay taps, e.g. 3333")
    p.add_argument("--pat", default=None,
                   help="pattern: prbs|worst|alt|hold")
    p.add_argument("--cansel", type=int, default=None, help="canary select 0..3")
    p.add_argument("--winsel", type=int, default=None,
                   help="canary window 0..3 or 256/1024/4096/16384 cycles")
    p.add_argument("--force-err", dest="force_err", type=int, default=None,
                   help="DFT: force DUT error (cfg[15])")
    p.add_argument("--force-can", dest="force_can", type=int, default=None,
                   help="DFT: mask canary loops (cfg[14])")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("pvtsweep", parents=[common],
                       help="first-failure clock period at one or all corners")
    p.add_argument("--corners", nargs="+", default=["all"],
                   help="corner names, or 'all' (default)")
    p.add_argument("--pmin", type=float, default=None, help="scan start (ns)")
    p.add_argument("--pmax", type=float, default=None, help="scan end (ns)")
    p.add_argument("--steps", type=int, default=None, help="grid points")
    p.add_argument("--tol", type=float, default=None,
                   help="bisection tolerance in ns")
    p.add_argument("--segs", default=None)
    p.add_argument("--pat", default=None)
    p.add_argument("--cansel", type=int, default=None)
    p.add_argument("--winsel", type=int, default=None)
    p.set_defaults(func=cmd_pvtsweep)

    p = sub.add_parser("selftest", parents=[common],
                       help="run the regression fixture")
    p.set_defaults(func=cmd_selftest)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    where = _resolve_toolchain(args.toolchain)
    if where == "devcontainer":
        _reexec_in_devcontainer(argv)
        raise SystemExit("failed to enter the devcontainer")

    # a PVT sweep is meaningless on the zero-delay RTL model
    if args.command == "pvtsweep" and "--backend" not in argv:
        args.backend = "sdf"

    if args.backend == "sdf" and args.corner is None and args.command in (
            "repl", "run", "selftest"):
        args.corner = "nom_typ_1p20V_25C"

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
