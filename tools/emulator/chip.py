# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""TpvChip: a cocotb driver that behaves like the physical test chip.

Two levels of control are exposed, matching the two ways people use the part:

Pin level (what a board or FPGA host does)
    chip.ui_in = 0x80            drive a byte onto the dedicated inputs
    chip.rst_n = 1               drive reset
    await chip.tick()            step one full clock cycle
    chip.uo_out, chip.uio_out    read the output pins

Protocol level (what the datasheet asks a host to do)
    await chip.configure(seg="3333", pat="worst")
    await chip.run_ops(100)
    await chip.set_freeze(True)
    st = await chip.read_status()
    st.err_cnt, st.ops, st.err_rate

The driver is backend-agnostic:

  * ``backend="rtl"``  zero-delay RTL: functional truth.  Timing does not
    depend on the clock period and PVT has no effect.
  * ``backend="sdf"``  post-route gate-level netlist with a per-corner SDF
    annotated: real cell delays, so PVT and clock period *do* change whether
    the DUT capture is correct.  Ring-oscillator canaries must be masked in
    this backend (their timing arcs are disabled for P&R), so canary counts
    are invalid and reported as zero.

Units are ns, MHz, volts, Celsius and clock cycles throughout.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import cocotb
from cocotb.triggers import Timer
from cocotb.utils import get_sim_time

from .pvt import PVT

FRAME_CYCLES = 19          # FRAME_LAST = 18 -> cycles 0..18
CAPTURE_DUTY = 0.5
TIME_QUANTUM_PS = 1        # simulator precision (timescale 1ns/1ps)


def quantize_ps(value_ns: float) -> int:
    """Snap a delay in ns to a whole number of picoseconds.

    Bisection produces periods like 15.25 ns whose quarter period (3.8125 ns)
    is not representable at 1 ps, and float ns values are not exact multiples
    of the simulator step.  Delays are therefore always passed to cocotb as
    integer picoseconds.
    """
    return int(round(float(value_ns) * 1000.0))


def quantize_ns(value_ns: float) -> float:
    """Quantized ns value, for reporting alongside the simulated delay."""
    return quantize_ps(value_ns) / 1000.0

PATTERN_NAMES = {0: "prbs", 1: "worst", 2: "alt", 3: "hold"}
PATTERN_SEL = {
    "prbs": 0, "prbs16": 0,
    "worst": 1, "worstcase": 1, "worst_case": 1, "carry": 1,
    "alt": 2, "alternating": 2, "carryfree": 2,
    "hold": 3, "static": 3,
}
WINDOW_CYCLES = {0: 256, 1: 1024, 2: 4096, 3: 16384}
WINDOW_SEL = {v: k for k, v in WINDOW_CYCLES.items()}


class ChipError(RuntimeError):
    """A pin or protocol misuse detected by the emulator."""


# --------------------------------------------------------------- config word --


def parse_segs(seg: Any) -> Tuple[int, int, int, int]:
    """Accept 3, (3,3,3,3), [3,3,3,3], "3333", "3,3,3,3" -> 4-tuple."""
    if isinstance(seg, int):
        if not 0 <= seg <= 3:
            raise ChipError("segment tap %r out of range 0..3" % seg)
        return (seg, seg, seg, seg)
    if isinstance(seg, str):
        text = seg.replace(",", " ").replace(":", " ")
        parts = [p for p in text.split() if p]
        if len(parts) == 1 and len(parts[0]) == 4:
            parts = list(parts[0])
        if len(parts) != 4:
            raise ChipError("cannot parse segment taps %r (want 4 values 0..3)" % seg)
        vals = tuple(int(p) for p in parts)
    elif isinstance(seg, (tuple, list)):
        vals = tuple(int(v) for v in seg)
    else:
        raise ChipError("cannot parse segment taps %r" % (seg,))
    if len(vals) != 4 or any(not 0 <= v <= 3 for v in vals):
        raise ChipError("segment taps must be four values in 0..3, got %r" % (vals,))
    return vals  # type: ignore[return-value]


def parse_pattern(pat: Any) -> int:
    if isinstance(pat, str):
        key = pat.strip().lower()
        if key in PATTERN_SEL:
            return PATTERN_SEL[key]
        try:
            pat = int(key, 0)
        except ValueError:
            raise ChipError(
                "unknown pattern %r (use prbs|worst|alt|hold or 0..3)" % pat)
    pat = int(pat)
    if not 0 <= pat <= 3:
        raise ChipError("pattern select %r out of range 0..3" % pat)
    return pat


def parse_window(winsel: Any) -> int:
    """Accept a window select 0..3 or a window length in cycles."""
    winsel = int(winsel) if not isinstance(winsel, str) else int(winsel, 0)
    if winsel in WINDOW_SEL:
        return WINDOW_SEL[winsel]
    if winsel in WINDOW_CYCLES:
        return WINDOW_CYCLES[winsel]
    raise ChipError(
        "window select %r: use 0..3 or one of %s cycles"
        % (winsel, "/".join(str(c) for c in sorted(WINDOW_CYCLES))))


def config_word(seg: Any = 0, pat: Any = 0, cansel: int = 0,
                winsel: Any = 0, force_can: int = 0,
                force_err: int = 0) -> int:
    """Build the 16-bit configuration word (ui_in = LSB, uio_in = MSB)."""
    s0, s1, s2, s3 = parse_segs(seg)
    p = parse_pattern(pat)
    w = parse_window(winsel)
    c = int(cansel)
    if not 0 <= c <= 3:
        raise ChipError("canary select %r out of range 0..3" % cansel)
    word = (
        (s0 & 3)
        | ((s1 & 3) << 2)
        | ((s2 & 3) << 4)
        | ((s3 & 3) << 6)
        | ((p & 3) << 8)
        | ((c & 3) << 10)
        | ((w & 3) << 12)
        | ((int(bool(force_can)) & 1) << 14)
        | ((int(bool(force_err)) & 1) << 15)
    )
    return word


def decode_config(word: int) -> Dict[str, Any]:
    word &= 0xFFFF
    return {
        "word": word,
        "seg": tuple((word >> (2 * k)) & 3 for k in range(4)),
        "pattern": PATTERN_NAMES[(word >> 8) & 3],
        "pat_sel": (word >> 8) & 3,
        "cansel": (word >> 10) & 3,
        "winsel": (word >> 12) & 3,
        "window_cycles": WINDOW_CYCLES[(word >> 12) & 3],
        "force_can": (word >> 14) & 1,
        "force_err": (word >> 15) & 1,
    }


# ------------------------------------------------------------------- status --


@dataclass
class Status:
    """Decoded 16-byte serial readout (see docs/info.md byte map)."""

    err_cnt: int = 0
    gen_cnt: int = 0
    mat_cnt: int = 0
    ops: int = 0
    cfg_echo: int = 0
    stat: int = 0
    err_dut: int = 0
    raw: Dict[int, int] = field(default_factory=dict)
    period_ns: float = 0.0
    duty: float = CAPTURE_DUTY
    backend: str = "rtl"
    pvt: Optional[PVT] = None
    sim_time_ns: float = 0.0

    # --- decoded flag bits (byte 9) ---
    @property
    def err_seen(self) -> bool:
        return bool((self.stat >> 4) & 1)

    @property
    def gen_dead(self) -> bool:
        return bool((self.stat >> 5) & 1)

    @property
    def mat_dead(self) -> bool:
        return bool((self.stat >> 6) & 1)

    @property
    def can_sel(self) -> int:
        return (self.stat >> 2) & 3

    @property
    def win_sel(self) -> int:
        return self.stat & 3

    @property
    def segs(self) -> str:
        return "".join(str((self.cfg_echo >> (2 * k)) & 3) for k in range(4))

    # --- derived measurement quantities ---
    @property
    def n_compared(self) -> int:
        """Operations whose result was actually checked (op 0 is not)."""
        return max(self.ops - 1, 0)

    @property
    def err_rate(self) -> float:
        return (self.err_cnt / self.n_compared) if self.n_compared else 0.0

    @property
    def failed(self) -> bool:
        return self.err_cnt > 0

    @property
    def high_time_ns(self) -> float:
        return self.period_ns * self.duty

    @property
    def freq_mhz(self) -> float:
        return 1e3 / self.period_ns if self.period_ns else 0.0

    def table(self) -> str:
        head = "PVT %s | backend %s | clk %.3f MHz (period %.4g ns, high %.4g ns)" % (
            self.pvt if self.pvt else "n/a", self.backend,
            self.freq_mhz, self.period_ns, self.high_time_ns)
        return "\n".join([
            head,
            "  ops          %5d   (compared %d)" % (self.ops, self.n_compared),
            "  err_cnt      %5d   err_rate %.4f per compared op" % (
                self.err_cnt, self.err_rate),
            "  err_seen     %5s   first failed byte 0x%02X" % (
                self.err_seen, self.err_dut),
            "  gen_cnt      %5d   mat_cnt %5d   (canary edges)" % (
                self.gen_cnt, self.mat_cnt),
            "  cfg_echo     0x%02X   segs %s   can_sel %d   win_sel %d (2^%d cyc)" % (
                self.cfg_echo, self.segs, self.can_sel, self.win_sel,
                8 + 2 * self.win_sel),
            "  flags        stat 0x%02X  gen_dead=%s mat_dead=%s" % (
                self.stat, self.gen_dead, self.mat_dead),
        ])


# -------------------------------------------------------------------- chip ----


class TpvChip:
    """Interactive model of tt_um_echoworld424_tpv."""

    def __init__(self, dut, *, pvt: Optional[PVT] = None, backend: str = "rtl",
                 period_ns: float = 100.0, duty: float = CAPTURE_DUTY,
                 force_can: Optional[int] = None, quiet: bool = False):
        self._tb = dut
        self._h = self._resolve(dut)
        self.backend = backend
        self.pvt = pvt
        self.quiet = quiet
        self._period_ns = float(period_ns)
        self._duty = float(duty)
        self._check_clock()
        # Ring oscillators cannot be simulated in the SDF backend: their SDF
        # arcs are disabled for P&R (see src/pnr.sdc), so the loop is zero
        # delay and the simulator would spin.  Mask them like run_sdfsim.py.
        if force_can is None:
            force_can = 1 if backend == "sdf" else 0
        elif backend == "sdf" and not force_can:
            raise ChipError(
                "backend='sdf' requires FORCE_CAN=1: the ring-oscillator loops "
                "have no annotated delay in the SDF and would livelock Icarus")
        self.force_can_default = int(bool(force_can))
        self.frozen = False
        self.last_config: Optional[Dict[str, Any]] = None
        self._init_pins()

    # -- handle plumbing ----------------------------------------------------

    @staticmethod
    def _resolve(dut):
        for name in ("ui_in", "uo_out"):
            if hasattr(dut, name):
                return dut
        if hasattr(dut, "user_project"):
            return dut.user_project
        raise ChipError("handle %r has no ui_in/uo_out pins" % (dut,))

    def _init_pins(self) -> None:
        self._pin_dirty = False
        self.clk = 0
        self.rst_n = 0
        self.ena = 1
        self.ui_in = 0
        self.uio_in = 0

    @property
    def handle(self):
        """The underlying cocotb handle (for advanced internal probing)."""
        return self._h

    # -- clock --------------------------------------------------------------

    def _check_clock(self) -> None:
        if self._period_ns <= 0:
            raise ChipError("clock period must be > 0 ns")
        if not 0.0 < self._duty < 1.0:
            raise ChipError("clock duty must be in (0,1)")

    @property
    def period_ns(self) -> float:
        return self._period_ns

    @period_ns.setter
    def period_ns(self, value: float) -> None:
        self._period_ns = float(value)
        self._check_clock()

    @property
    def duty(self) -> float:
        return self._duty

    @duty.setter
    def duty(self, value: float) -> None:
        self._duty = float(value)
        self._check_clock()

    @property
    def t_high_ns(self) -> float:
        return quantize_ns(self._period_ns * self._duty)

    @property
    def t_low_ns(self) -> float:
        return quantize_ns(self._period_ns * (1.0 - self._duty))

    @property
    def t_high_ps(self) -> int:
        return quantize_ps(self._period_ns * self._duty)

    @property
    def t_low_ps(self) -> int:
        return quantize_ps(self._period_ns * (1.0 - self._duty))

    @property
    def freq_mhz(self) -> float:
        return 1e3 / self._period_ns

    @property
    def time_ns(self) -> float:
        return float(get_sim_time("ns"))

    async def _settle_pins(self) -> None:
        """Let a pin change land before the next clock edge.

        cocotb deposits a pin write and a clock write at the same simulation
        time; without a delta of separation the edge can be evaluated with the
        old pin value (the same zero-delay race the cocotb suite documents).
        One picosecond is far below the 1 ns timescale and does not change the
        clock high time, i.e. the measurement aperture.
        """
        if self._pin_dirty:
            await Timer(TIME_QUANTUM_PS, "ps")
            self._pin_dirty = False

    async def half(self, level: int, hold_ns: Optional[float] = None):
        """Drive clk to ``level`` and hold it for a half period."""
        await self._settle_pins()
        self._h.clk.value = 1 if level else 0
        if hold_ns is None:
            hold_ns = self.t_high_ns if level else self.t_low_ns
        await Timer(quantize_ps(hold_ns), "ps")

    async def tick(self, n: int = 1):
        """Advance ``n`` complete clock cycles (rising edge first)."""
        await self._settle_pins()
        for _ in range(int(n)):
            self._h.clk.value = 1
            await Timer(self.t_high_ps, "ps")
            self._h.clk.value = 0
            await Timer(self.t_low_ps, "ps")

    #: alias, so both `await chip.tick()` and `await chip.cycle()` read well
    cycle = tick

    async def cycles(self, n: int):
        await self.tick(n)

    # -- pins ---------------------------------------------------------------

    def _raw(self, name: str):
        return getattr(self._h, name).value

    def _get(self, name: str) -> int:
        raw = self._raw(name)
        try:
            return int(raw)
        except ValueError as exc:
            raise ChipError(
                "%s is not fully resolved (%s); apply reset first"
                % (name, raw)) from exc

    def _get_opt(self, name: str) -> Optional[int]:
        """Like ``_get`` but returns None for unresolved (X/Z) pins."""
        try:
            return int(self._raw(name))
        except ValueError:
            return None

    def _drive(self, name: str, value: int) -> None:
        getattr(self._h, name).value = int(value)
        self._pin_dirty = True

    @property
    def ui_in(self) -> int:
        return self._get("ui_in")

    @ui_in.setter
    def ui_in(self, value: int) -> None:
        self._drive("ui_in", int(value) & 0xFF)

    ui = ui_in  # datasheet spelling: ui[7:0]

    @property
    def uio_in(self) -> int:
        return self._get("uio_in")

    @uio_in.setter
    def uio_in(self, value: int) -> None:
        self._drive("uio_in", int(value) & 0xFF)

    uio = uio_in

    @property
    def rst_n(self) -> int:
        return self._get("rst_n")

    @rst_n.setter
    def rst_n(self, value: int) -> None:
        self._drive("rst_n", int(value) & 1)

    @property
    def ena(self) -> int:
        return self._get("ena")

    @ena.setter
    def ena(self, value: int) -> None:
        self._drive("ena", int(value) & 1)

    @property
    def clk(self) -> int:
        return self._get("clk")

    @clk.setter
    def clk(self, value: int) -> None:
        self._drive("clk", int(value) & 1)

    @property
    def uo_out(self) -> int:
        return self._get("uo_out")

    @property
    def uio_out(self) -> int:
        return self._get("uio_out")

    @property
    def uio_oe(self) -> int:
        return self._get("uio_oe")

    @property
    def frame_strobe(self) -> int:
        return (self.uo_out >> 7) & 1

    @property
    def dut_err_pin(self) -> int:
        return (self.uo_out >> 4) & 1

    def pins(self) -> Dict[str, Any]:
        """All pin values; None where a pin is still unresolved (X/Z)."""
        uo = self._get_opt("uo_out")
        return {
            "time_ns": self.time_ns,
            "clk": self._get_opt("clk"),
            "rst_n": self._get_opt("rst_n"),
            "ena": self._get_opt("ena"),
            "ui_in": self._get_opt("ui_in"),
            "uio_in": self._get_opt("uio_in"),
            "uo_out": uo,
            "uio_out": self._get_opt("uio_out"),
            "uio_oe": self._get_opt("uio_oe"),
            "ro_ptr": None if uo is None else uo & 0xF,
            "frame_strobe": None if uo is None else (uo >> 7) & 1,
            "dut_err": None if uo is None else (uo >> 4) & 1,
            "frozen": self.frozen,
        }

    @staticmethod
    def _hex(value: Optional[int], width: int = 2) -> str:
        return "-" * width if value is None else ("%0*X" % (width, value))

    @staticmethod
    def _bit(value: Optional[int]) -> str:
        return "?" if value is None else str(value)

    def pin_report(self) -> str:
        p = self.pins()
        return "\n".join([
            "  t=%-10.3f ns  clk=%s rst_n=%s ena=%s" % (
                p["time_ns"], self._bit(p["clk"]), self._bit(p["rst_n"]),
                self._bit(p["ena"])),
            "  in : ui_in=0x%s uio_in=0x%s" % (
                self._hex(p["ui_in"]), self._hex(p["uio_in"])),
            "  out: uo_out=0x%s uio_out=0x%s uio_oe=0x%s" % (
                self._hex(p["uo_out"]), self._hex(p["uio_out"]),
                self._hex(p["uio_oe"])),
            "       ro_ptr=%s frame_strobe=%s dut_err=%s frozen=%s" % (
                self._bit(p["ro_ptr"]), self._bit(p["frame_strobe"]),
                self._bit(p["dut_err"]), p["frozen"]),
        ])

    def peek(self, path: str) -> Optional[int]:
        """Read an internal signal by name; None if it does not exist."""
        node = self._h
        for part in path.split("."):
            if not hasattr(node, part):
                return None
            node = getattr(node, part)
        try:
            return int(node.value)
        except (ValueError, TypeError, AttributeError):
            return None

    # -- protocol -----------------------------------------------------------

    async def reset(self, cycles: int = 4):
        """Assert reset with clk low and step ``cycles`` clocks."""
        self.clk = 0
        self.rst_n = 0
        await self.tick(cycles)
        self.frozen = False

    async def configure(self, word: Optional[int] = None, *, seg: Any = 0,
                        pat: Any = 0, cansel: int = 0, winsel: Any = 0,
                        force_can: Optional[int] = None, force_err: int = 0,
                        boot_cycles: int = 3, settle: int = 8) -> int:
        """Reset the chip and commit a configuration word.

        Protocol (docs/info.md): drive {uio_in, ui_in} while rst_n is low,
        release reset during the low phase, keep the word stable through the
        third rising edge (the boot counter commits it at boot==2), then
        release the pins with ui_in[7]=0 so the run is not frozen.
        """
        if word is None:
            if force_can is None:
                force_can = self.force_can_default
            word = config_word(seg=seg, pat=pat, cansel=cansel, winsel=winsel,
                               force_can=force_can, force_err=force_err)
        word = int(word) & 0xFFFF
        if self.backend == "sdf" and not (word >> 14) & 1:
            raise ChipError(
                "backend='sdf' cannot run with FORCE_CAN=0 (cfg[14]=0): the ring "
                "oscillators have no annotated delay and would livelock Icarus; "
                "set force_can=1 (the SDF backend default)")
        self.last_config = decode_config(word)

        self.clk = 0
        self.rst_n = 0
        self.ui_in = word & 0xFF
        self.uio_in = (word >> 8) & 0xFF
        await self.tick(4)
        self.rst_n = 1
        # release during the low phase, before the first counted rising edge
        await Timer(quantize_ps(self.t_low_ns / 2.0), "ps")
        await self.tick(boot_cycles)
        self.ui_in = 0          # ui_in[7] = FREEZE must be low
        self.uio_in = 0         # host switches uio to inputs; chip drives it
        await self.tick(settle)
        self.frozen = False
        return word

    #: datasheet wording
    boot = configure

    async def set_freeze(self, on: bool = True, settle: int = 2):
        self.ui_in = 0x80 if on else 0x00
        await self.tick(settle)
        self.frozen = bool(on)

    async def run_ops(self, ops: int):
        """Advance ``ops`` frame periods (19 clock cycles each)."""
        await self.tick(int(ops) * FRAME_CYCLES)

    async def run_cycles(self, cycles: int):
        await self.tick(int(cycles))

    async def read_status(self, max_cycles: int = 48) -> Status:
        """Sample all 16 readout bytes through the auto-incrementing pointer."""
        if self.uio_oe != 0xFF:
            raise ChipError(
                "uio is not driving (uio_oe=0x%02X): the chip is still in the "
                "configuration phase; call configure() first" % self.uio_oe)
        if not self.frozen:
            print("[emulator] note: reading status while not frozen; counters "
                  "can change between bytes (freeze first for a coherent "
                  "snapshot)", flush=True)
        vals: Dict[int, int] = {}
        for _ in range(int(max_cycles)):
            self._h.clk.value = 1
            await Timer(self.t_high_ps, "ps")
            ptr = self.uo_out & 0xF
            vals[ptr] = self.uio_out
            self._h.clk.value = 0
            await Timer(self.t_low_ps, "ps")
            if len(vals) == 16:
                break
        if len(vals) != 16:
            raise ChipError("incomplete readout: got pointers %s" % sorted(vals))
        st = Status(
            err_cnt=vals[0] | (vals[1] << 8),
            gen_cnt=vals[2] | (vals[3] << 8),
            mat_cnt=vals[4] | (vals[5] << 8),
            ops=vals[6] | (vals[7] << 8),
            cfg_echo=vals[8],
            stat=vals[9],
            err_dut=vals[10],
            raw=dict(vals),
            period_ns=self._period_ns,
            duty=self._duty,
            backend=self.backend,
            pvt=self.pvt,
            sim_time_ns=self.time_ns,
        )
        return st

    async def measure(self, ops: int = 100, *, resume: bool = False,
                      **cfg: Any) -> Status:
        """configure -> run -> freeze -> read (one complete measurement)."""
        await self.configure(**cfg)
        await self.run_ops(ops)
        await self.set_freeze(True)
        st = await self.read_status()
        if resume:
            await self.set_freeze(False)
        return st

    async def sweep_period(self, periods, ops: int = 100, **cfg: Any):
        """Run one measurement per clock period; returns [(period_ns, Status)]."""
        out = []
        for period in periods:
            self.period_ns = float(period)
            st = await self.measure(ops, **cfg)
            out.append((float(period), st))
        return out

    async def find_failure_period(self, p_fail: float, p_pass: float,
                                  ops: int = 100, tol_ns: float = 0.25,
                                  max_iter: int = 12, verbose: bool = True,
                                  **cfg: Any):
        """Bisect the first-failing clock period between p_fail < p_pass.

        The DUT fails when the clock high time is too short, so error rate is
        monotone in the period over the interesting range.  Returns
        ``(p_pass_ns, p_fail_ns, trace)``: the tightest bracket found, where
        ``p_fail_ns`` is the largest period observed to fail and ``p_pass_ns``
        the smallest observed to pass (both None when no bracket exists).
        """
        if not p_fail < p_pass:
            raise ChipError("need p_fail < p_pass (got %g, %g)" % (p_fail, p_pass))
        trace = []

        async def probe(period):
            self.period_ns = float(period)
            st = await self.measure(ops, **cfg)
            trace.append((float(period), st.err_cnt, st.ops))
            if verbose:
                print("    probe %8.4f ns (%7.3f MHz) high %6.4f ns -> "
                      "err %5d / %5d" % (period, st.freq_mhz, st.high_time_ns,
                                         st.err_cnt, st.n_compared))
            return st.failed

        fails_at_lo = await probe(p_fail)
        fails_at_hi = await probe(p_pass)
        if not fails_at_lo:
            if verbose:
                print("    no failure at %.4f ns: boundary is below p_fail" % p_fail)
            return None, None, trace
        if fails_at_hi:
            if verbose:
                print("    errors already at %.4f ns: boundary is above p_pass" % p_pass)
            return None, None, trace
        lo, hi = float(p_fail), float(p_pass)   # lo fails, hi passes
        while (hi - lo) > tol_ns and len(trace) < max_iter + 2:
            mid = 0.5 * (lo + hi)
            if await probe(mid):
                lo = mid
            else:
                hi = mid
        if verbose:
            print("    bracket: fails at %.4f ns, passes at %.4f ns"
                  % (lo, hi))
        return hi, lo, trace

    # -- reporting ----------------------------------------------------------

    def describe(self) -> str:
        lines = [
            "backend : %s%s" % (
                self.backend,
                " (post-route netlist + corner SDF: PVT-dependent)"
                if self.backend == "sdf" else
                " (zero-delay RTL: functional, PVT-independent)"),
            "PVT     : %s" % (self.pvt if self.pvt else "n/a (RTL)"),
            "clock   : %.4g ns period, duty %.3f -> %.3f MHz, high %.4g ns" % (
                self._period_ns, self._duty, self.freq_mhz, self.t_high_ns),
            "frame   : %d clock cycles per measured operation" % FRAME_CYCLES,
            "sim     : %s %s, cocotb %s, python %s" % (
                getattr(cocotb, "SIM_NAME", "?"), getattr(cocotb, "SIM_VERSION", "?"),
                getattr(cocotb, "__version__", getattr(cocotb, "VERSION", "?")),
                sys.version.split()[0]),
        ]
        if self.last_config:
            c = self.last_config
            lines.append("config  : 0x%04X seg=%s pat=%s cansel=%d window=%d cyc"
                         " force_can=%d force_err=%d" % (
                             c["word"], "".join(str(s) for s in c["seg"]),
                             c["pattern"], c["cansel"], c["window_cycles"],
                             c["force_can"], c["force_err"]))
        return "\n".join(lines)
