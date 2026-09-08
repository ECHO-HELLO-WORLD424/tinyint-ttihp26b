# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Ready-made experiments for the chip emulator.

Every scenario is ``async def scenario(chip, opts) -> int`` where ``opts`` is
the cocotb plusarg dictionary (all values are strings).  Returning non-zero
fails the cocotb test, which is how ``selftest`` acts as a regression fixture.

Run one with::

    python3 tools/chip_emulate.py run hello --backend sdf --corner slow
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import cocotb

from .chip import FRAME_CYCLES, Status, config_word

# Default clock-period scan range per corner (ns).  The failure boundary of
# the predeclared seg=3333 / worst-carry configuration lies inside these
# ranges at every corner (see data/*/sdfsim.csv).
SWEEP_RANGE = {
    "nom_fast_1p32V_m40C": (6.0, 24.0),
    "nom_typ_1p20V_25C": (8.0, 32.0),
    "nom_slow_1p08V_125C": (14.0, 48.0),
}


def _f(opts: Dict[str, str], key: str, default: float) -> float:
    try:
        return float(opts[key])
    except (KeyError, TypeError, ValueError):
        return float(default)


def _i(opts: Dict[str, str], key: str, default: int) -> int:
    try:
        return int(opts[key])
    except (KeyError, TypeError, ValueError):
        return int(default)


def _s(opts: Dict[str, str], key: str, default: str = "") -> str:
    value = opts.get(key, default)
    return default if value is True or value is None else str(value)


def _cfg_from(opts: Dict[str, str]) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "seg": _s(opts, "segs", "0000"),
        "pat": _s(opts, "pat", "prbs"),
        "cansel": _i(opts, "cansel", 0),
        "winsel": _i(opts, "winsel", 0),
    }
    if "force_err" in opts:
        cfg["force_err"] = _i(opts, "force_err", 0)
    if "force_can" in opts:
        cfg["force_can"] = _i(opts, "force_can", 0)
    return cfg


def _status_dict(st: Status) -> Dict[str, Any]:
    """JSON-friendly view of one measurement."""
    return {
        "ops": st.ops, "n_compared": st.n_compared,
        "err_cnt": st.err_cnt, "err_rate": st.err_rate,
        "err_seen": st.err_seen, "err_dut_byte": st.err_dut,
        "gen_cnt": st.gen_cnt, "mat_cnt": st.mat_cnt,
        "gen_dead": st.gen_dead, "mat_dead": st.mat_dead,
        "cfg_echo": st.cfg_echo, "segs": st.segs,
        "can_sel": st.can_sel, "win_sel": st.win_sel, "stat": st.stat,
        "period_ns": st.period_ns, "freq_mhz": st.freq_mhz,
        "high_time_ns": st.high_time_ns, "duty": st.duty,
        "backend": st.backend, "sim_time_ns": st.sim_time_ns,
        "pvt": ({"name": st.pvt.name, "voltage_v": st.pvt.voltage_v,
                 "temp_c": st.pvt.temp_c} if st.pvt else None),
    }


def _check(name: str, ok: bool, detail: str, failures: List[str]) -> bool:
    print("  [%s] %s: %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)
    if not ok:
        failures.append(name)
    return ok


def _provenance(chip) -> Dict[str, Any]:
    """Identity of everything that produced a measurement."""
    opts = dict(cocotb.plusargs)
    prov = {
        "backend": chip.backend,
        "corner": chip.pvt.name if chip.pvt else None,
        "voltage_v": chip.pvt.voltage_v if chip.pvt else None,
        "temp_c": chip.pvt.temp_c if chip.pvt else None,
        "clock_period_ns": chip.period_ns,
        "clock_duty": chip.duty,
        "frame_cycles": FRAME_CYCLES,
        "netlist": opts.get("netlist_source"),
        "netlist_sha256": opts.get("netlist_sha256"),
        "sdf": opts.get("sdf_source"),
        "sdf_sha256": opts.get("sdf_sha256"),
        "sim": "%s %s" % (getattr(cocotb, "SIM_NAME", "?"),
                          getattr(cocotb, "SIM_VERSION", "?")),
        "cocotb": getattr(cocotb, "__version__", "?"),
    }
    return {k: v for k, v in prov.items() if v is not None}


def _write_json(path: str, payload: Dict[str, Any], chip=None) -> str:
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload.setdefault("generated_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                      time.gmtime()))
    if chip is not None:
        payload.setdefault("provenance", _provenance(chip))
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=False)
    print("  wrote %s" % path, flush=True)
    return path


# ---------------------------------------------------------------- scenarios --


async def hello(chip, opts) -> int:
    """One measurement, decoded and printed."""
    ops = _i(opts, "ops", 20)
    st = await chip.measure(ops, **_cfg_from(opts))
    print(st.table(), flush=True)
    if _s(opts, "out"):
        _write_json(_s(opts, "out"),
                    {"scenario": "hello", "status": _status_dict(st)}, chip)
    return 0


async def pins(chip, opts) -> int:
    """Pin-level walkthrough: drive pins, step single clock cycles."""
    word = config_word(seg=_s(opts, "segs", "3333"), pat=_s(opts, "pat", "worst"),
                       cansel=_i(opts, "cansel", 1), winsel=_i(opts, "winsel", 0),
                       force_can=chip.force_can_default)

    # 1. reset phase: uio is an input, the config word is on the pins
    chip.clk = 0
    chip.rst_n = 0
    chip.ui_in = word & 0xFF
    chip.uio_in = (word >> 8) & 0xFF
    await chip.tick(2)
    print("\n[1] reset phase, config word 0x%04X on the pins:" % word, flush=True)
    print(chip.pin_report(), flush=True)
    print("    uio_oe = 0x%02X -> uio is an input (host drives it)" % chip.uio_oe,
          flush=True)

    # 2. release reset, keep the word stable for the 3-cycle boot window
    chip.rst_n = 1
    await chip.tick(3)
    print("\n[2] after 3 boot clocks (config committed):", flush=True)
    print(chip.pin_report(), flush=True)
    print("    uio_oe = 0x%02X -> uio is now the status output" % chip.uio_oe,
          flush=True)

    # 3. step single cycles and watch the frame strobe (uo[7])
    chip.ui_in = 0x00
    chip.uio_in = 0x00
    print("\n[3] stepping single clock cycles (uo[7]=frame_strobe, uo[3:0]=ptr):",
          flush=True)
    strobes = 0
    for n in range(2 * FRAME_CYCLES + 3):
        await chip.tick()
        p = chip.pins()
        strobes += p["frame_strobe"] or 0
        if n < 6 or p["frame_strobe"]:
            print("    cycle %2d: t=%8.1f ns  ptr=%s strobe=%s uio_out=0x%s"
                  % (n, p["time_ns"], chip._bit(p["ro_ptr"]),
                     chip._bit(p["frame_strobe"]), chip._hex(p["uio_out"])),
                  flush=True)
    ok = _check("frame pacing", strobes == 2,
                "%d frame strobes in %d cycles (expect 2)" % (
                    strobes, 2 * FRAME_CYCLES + 3), [])
    await chip.run_ops(5)

    # 4. freeze with ui_in[7] while the clock keeps running
    print("\n[4] FREEZE (ui_in[7]=1) with the clock still running:", flush=True)
    await chip.set_freeze(True)
    before = await chip.read_status()
    await chip.tick(3 * FRAME_CYCLES)
    after = await chip.read_status()
    print(before.table(), flush=True)
    _check("freeze holds counters",
           (before.err_cnt, before.ops) == (after.err_cnt, after.ops),
           "ops %d->%d err %d->%d" % (before.ops, after.ops,
                                      before.err_cnt, after.err_cnt), [])
    await chip.set_freeze(False)
    print("\n[5] resumed: uo[7:4] = {strobe, mat_dead, gen_dead, dut_err}", flush=True)
    await chip.run_ops(2)
    print(chip.pin_report(), flush=True)
    return 0 if ok else 1


async def patterns(chip, opts) -> int:
    """Error rate across the four workload classes and several delay taps."""
    ops = _i(opts, "ops", 50)
    seg_list = _s(opts, "seg_list", "0000,1111,3333").split(",")
    print("\n  %-8s %-6s %8s %8s %8s" % ("segs", "pat", "ops", "err", "err/op"),
          flush=True)
    rows = []
    for segs in seg_list:
        for pat in ("prbs", "worst", "alt", "hold"):
            st = await chip.measure(ops, seg=segs, pat=pat,
                                    cansel=_i(opts, "cansel", 0),
                                    winsel=_i(opts, "winsel", 0))
            rows.append({"segs": segs, "pat": pat, "ops": st.ops,
                         "err_cnt": st.err_cnt, "err_rate": st.err_rate})
            print("  %-8s %-6s %8d %8d %8.4f" % (
                segs, pat, st.ops, st.err_cnt, st.err_rate), flush=True)
    if _s(opts, "out"):
        _write_json(_s(opts, "out"), {"scenario": "patterns", "rows": rows}, chip)
    return 0


async def dft(chip, opts) -> int:
    """Exercise the FORCE_ERR / FORCE_CAN design-for-test paths."""
    ops = _i(opts, "ops", 20)
    failures: List[str] = []

    st = await chip.measure(ops, seg="3333", pat="worst", cansel=1, winsel=0,
                            force_err=1)
    print("\nFORCE_ERR=1:\n" + st.table(), flush=True)
    _check("force_err accounting", st.err_cnt == max(st.ops - 1, 0),
           "err_cnt=%d, compared=%d" % (st.err_cnt, st.n_compared), failures)
    _check("first-error flag", st.err_seen, "err_seen=%s" % st.err_seen, failures)

    # The dead flags only assert once the canary window has completed, so the
    # FORCE_CAN run needs at least the 2^8-cycle window (winsel=0).
    st2 = await chip.measure(max(ops, 20), seg="3333", pat="worst", cansel=1,
                             winsel=0, force_can=1, force_err=0)
    print("\nFORCE_CAN=1 (loops stalled, counters must stay zero):\n" + st2.table(),
          flush=True)
    _check("force_can stalls loops", st2.gen_cnt == 0 and st2.mat_cnt == 0,
           "gen=%d mat=%d" % (st2.gen_cnt, st2.mat_cnt), failures)
    _check("dead flags", st2.gen_dead and st2.mat_dead,
           "gen_dead=%s mat_dead=%s" % (st2.gen_dead, st2.mat_dead), failures)
    _check("no false errors", st2.err_cnt == 0, "err_cnt=%d" % st2.err_cnt,
           failures)

    st3 = await chip.measure(ops, seg="3333", pat="worst", cansel=1, winsel=0)
    print("\nnormal run (no DFT bits):\n" + st3.table(), flush=True)
    return 1 if failures else 0


async def pvtsweep(chip, opts) -> int:
    """Scan clock period at the selected corner and find the first failure."""
    ops = _i(opts, "ops", 100)
    corner_name = chip.pvt.name if chip.pvt else "nom_typ_1p20V_25C"
    default_lo, default_hi = SWEEP_RANGE.get(corner_name, (8.0, 60.0))
    pmin = _f(opts, "pmin", default_lo)
    pmax = _f(opts, "pmax", default_hi)
    steps = max(_i(opts, "steps", 9), 2)
    tol = _f(opts, "tol", 0.25)
    cfg = _cfg_from(opts)
    word = config_word(seg=cfg["seg"], pat=cfg["pat"], cansel=cfg["cansel"],
                       winsel=cfg["winsel"],
                       force_can=cfg.get("force_can", chip.force_can_default),
                       force_err=cfg.get("force_err", 0))

    print("\n  clock-period scan, config 0x%04X, %d ops per point:" % (word, ops),
          flush=True)
    print("  %10s %10s %10s %8s %8s %10s" % (
        "period_ns", "freq_MHz", "high_ns", "ops", "err", "err/op"), flush=True)

    periods = [pmin + (pmax - pmin) * i / (steps - 1) for i in range(steps)]
    rows: List[Dict[str, Any]] = []
    for period in periods:
        chip.period_ns = period
        st = await chip.measure(ops, **cfg)
        rows.append({"period_ns": period, "freq_mhz": st.freq_mhz,
                     "high_time_ns": st.high_time_ns, "ops": st.ops,
                     "err_cnt": st.err_cnt, "err_rate": st.err_rate,
                     "gen_cnt": st.gen_cnt, "mat_cnt": st.mat_cnt})
        print("  %10.4f %10.3f %10.4f %8d %8d %10.4f" % (
            period, st.freq_mhz, st.high_time_ns, st.ops, st.err_cnt,
            st.err_rate), flush=True)

    failing = [r for r in rows if r["err_cnt"] > 0]
    passing = [r for r in rows if r["err_cnt"] == 0]
    fail_below = max((r["period_ns"] for r in failing), default=None)
    pass_above = min((r["period_ns"] for r in passing), default=None)
    if not failing:
        print("\n  no failure in %.3f..%.3f ns" % (pmin, pmax), flush=True)
        if chip.backend == "rtl":
            print("  (RTL is zero-delay: use --backend sdf for PVT timing)",
                  flush=True)
    else:
        slowest_fail = max(failing, key=lambda r: r["period_ns"])
        print("\n  lowest failing grid point: %.4f ns (%.3f MHz), high %.4f ns"
              % (min(failing, key=lambda r: r["period_ns"])["period_ns"],
                 min(failing, key=lambda r: r["period_ns"])["freq_mhz"],
                 min(failing, key=lambda r: r["period_ns"])["high_time_ns"]),
              flush=True)
        if pass_above is not None and pass_above > slowest_fail["period_ns"]:
            print("  bisecting between %.4f ns (fails) and %.4f ns (passes):"
                  % (slowest_fail["period_ns"], pass_above), flush=True)
            boundary, last_fail, trace = await chip.find_failure_period(
                slowest_fail["period_ns"], pass_above, ops=ops, tol_ns=tol, **cfg)
            for period, err, nops in trace:
                rows.append({"period_ns": period, "ops": nops, "err_cnt": err,
                             "source": "bisection"})
            if boundary is not None:
                pass_above, fail_below = boundary, last_fail
        if fail_below is not None and pass_above is not None:
            print("\n  boundary: fails at %.4f ns, passes at %.4f ns "
                  "-> f_fail in [%.3f, %.3f] MHz"
                  % (fail_below, pass_above, 1e3 / pass_above, 1e3 / fail_below),
                  flush=True)

    payload = {
        "scenario": "pvtsweep",
        "corner": chip.pvt.name if chip.pvt else None,
        "pvt": {"voltage_v": chip.pvt.voltage_v, "temp_c": chip.pvt.temp_c}
        if chip.pvt else None,
        "backend": chip.backend,
        "config": chip.last_config,
        "ops_per_point": ops,
        "rows": rows,
        "boundary_fail_period_ns": fail_below,
        "boundary_pass_period_ns": pass_above,
        "boundary_freq_mhz": (1e3 / pass_above) if pass_above else None,
    }
    if _s(opts, "out"):
        _write_json(_s(opts, "out"), payload, chip)
    return 0


async def selftest(chip, opts) -> int:
    """Regression fixture: protocol, counters, DFT, freeze, PVT behavior."""
    failures: List[str] = []

    # 1. protocol and functional correctness
    st = await chip.measure(20, seg="3333", pat="worst", cansel=1, winsel=0)
    _check("config echo", st.cfg_echo == 0xFF,
           "cfg_echo=0x%02X segs=%s" % (st.cfg_echo, st.segs), failures)
    _check("op count", st.ops == 20, "ops=%d" % st.ops, failures)
    _check("uio drives after boot", chip.uio_oe == 0xFF,
           "uio_oe=0x%02X" % chip.uio_oe, failures)

    # 2. FORCE_ERR accounting
    st = await chip.measure(10, seg="0000", pat="prbs", force_err=1)
    _check("force_err accounting", st.err_cnt == 9,
           "err_cnt=%d (expect 9)" % st.err_cnt, failures)
    _check("err_seen", st.err_seen, "err_seen=%s" % st.err_seen, failures)

    # 3. canaries
    if chip.backend == "rtl":
        st = await chip.measure(30, seg="0000", pat="hold", cansel=3, winsel=0)
        _check("RO canaries oscillate", st.gen_cnt > 0 and st.mat_cnt > 0,
               "gen=%d mat=%d" % (st.gen_cnt, st.mat_cnt), failures)
    else:
        st = await chip.measure(20, seg="3333", pat="worst", cansel=1, winsel=0)
        _check("canaries masked in SDF backend",
               st.gen_cnt == 0 and st.mat_cnt == 0 and st.gen_dead and st.mat_dead,
               "gen=%d mat=%d dead=%s/%s" % (st.gen_cnt, st.mat_cnt,
                                             st.gen_dead, st.mat_dead), failures)

    # 4. freeze holds measurement state
    await chip.set_freeze(True)
    a = await chip.read_status()
    await chip.tick(3 * FRAME_CYCLES)
    b = await chip.read_status()
    _check("freeze holds counters", (a.ops, a.err_cnt) == (b.ops, b.err_cnt),
           "ops %d->%d err %d->%d" % (a.ops, b.ops, a.err_cnt, b.err_cnt),
           failures)
    await chip.set_freeze(False)

    # 5. reconfiguration clears counters
    await chip.configure(seg="0000", pat="hold", force_err=1)
    await chip.run_ops(5)
    await chip.set_freeze(True)
    st = await chip.read_status()
    _check("reconfigure clears counters", st.err_cnt == max(st.ops - 1, 0),
           "err_cnt=%d ops=%d" % (st.err_cnt, st.ops), failures)
    await chip.set_freeze(False)

    # 6. timing behavior: long period must pass, very short period must fail
    chip.period_ns = 60.0
    st_slow = await chip.measure(20, seg="3333", pat="worst", cansel=1, winsel=0)
    _check("clean at 60 ns", st_slow.err_cnt == 0,
           "err_cnt=%d ops=%d" % (st_slow.err_cnt, st_slow.ops), failures)
    chip.period_ns = 8.0
    st_fast = await chip.measure(20, seg="3333", pat="worst", cansel=1, winsel=0)
    if chip.backend == "rtl":
        _check("RTL is zero-delay at 8 ns", st_fast.err_cnt == 0,
               "err_cnt=%d (RTL timing is PVT-independent)" % st_fast.err_cnt,
               failures)
    else:
        _check("timing failure at 8 ns", st_fast.err_cnt > 0,
               "err_cnt=%d/%d at %.1f ns" % (st_fast.err_cnt, st_fast.n_compared,
                                             8.0), failures)
        st_again = await chip.measure(20, seg="3333", pat="worst", cansel=1,
                                      winsel=0)
        _check("deterministic failure count",
               st_again.err_cnt == st_fast.err_cnt,
               "%d vs %d" % (st_fast.err_cnt, st_again.err_cnt), failures)

    print("\n%s: %d check(s) failed%s" % (
        "SELFTEST FAIL" if failures else "SELFTEST PASS", len(failures),
        (": " + ", ".join(failures)) if failures else ""), flush=True)
    return 1 if failures else 0


SCENARIOS = {
    "hello": hello,
    "pins": pins,
    "patterns": patterns,
    "dft": dft,
    "pvtsweep": pvtsweep,
    "selftest": selftest,
}
