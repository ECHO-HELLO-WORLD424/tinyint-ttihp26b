# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Interactive command loop for the chip emulator.

The loop runs inside the cocotb test (``session.py``), so every command can
await real simulation time: ``tick`` advances one clock cycle, ``run`` advances
frames, and ``status`` reads the chip's serial readout.

The same engine executes command scripts, which is how the usage examples in
``tools/emulator/README.md`` are reproduced:

    python3 tools/chip_emulate.py repl --script examples/pin_level.txt
"""

from __future__ import annotations

import os
import shlex
import sys
from typing import Any, Dict, List, Optional

from .chip import FRAME_CYCLES, ChipError, Status, config_word, decode_config


class ReplError(Exception):
    """A command failed (bad arguments or a failed assertion)."""


class ReplStop(Exception):
    """Quit requested."""


def parse_int(text: str) -> int:
    """Accept 0x1F, 0b1111, 0o17 and plain decimal."""
    try:
        return int(str(text), 0)
    except ValueError:
        raise ReplError("not an integer: %r" % text)


class Repl:
    def __init__(self, chip, out=None):
        self.chip = chip
        self.out = out or sys.stdout
        self.last_status: Optional[Status] = None
        self.last_sweep: List[Any] = []
        self.prompt = "tpv> "
        self._interactive = sys.stdin.isatty()

    # -- output -------------------------------------------------------------

    def print(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("file", self.out)
        kwargs.setdefault("flush", True)
        print(*args, **kwargs)

    # -- command dispatch ---------------------------------------------------

    async def execute(self, line: str) -> bool:
        """Run one command line.  Returns False when the session should end."""
        line = line.strip()
        if not line or line.startswith("#"):
            return True
        try:
            argv = shlex.split(line, comments=True)
        except ValueError as exc:
            raise ReplError("cannot parse %r: %s" % (line, exc))
        if not argv:
            return True
        name, args = argv[0].lower(), argv[1:]
        handler = getattr(self, "cmd_" + name.replace("-", "_"), None)
        if handler is None:
            raise ReplError("unknown command %r (try 'help')" % name)
        await handler(*args)
        return name not in ("quit", "exit")

    async def run(self, lines: Optional[List[str]] = None,
                  strict: bool = False) -> int:
        """Interactive loop (``lines is None``) or script execution."""
        if lines is not None:
            for lineno, line in enumerate(lines, 1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                try:
                    if not await self.execute(line):
                        break
                except (ReplError, ChipError) as exc:
                    raise ReplError("script line %d (%r): %s"
                                    % (lineno, line.strip(), exc))
            return 0

        self.print("tpv chip emulator -- type 'help' for commands, 'quit' to exit")
        while True:
            try:
                if self._interactive:
                    self.print(self.prompt, end="")
                raw = sys.stdin.readline()
            except KeyboardInterrupt:
                self.print("")
                break
            if raw == "":            # EOF
                self.print("")
                break
            try:
                if not await self.execute(raw):
                    break
            except (ReplError, ChipError) as exc:
                self.print("error: %s" % exc)
            except KeyboardInterrupt:
                self.print("\ninterrupted")
        return 0

    async def run_file(self, path: str, strict: bool = True) -> int:
        with open(path) as fh:
            lines = fh.read().splitlines()
        self.print("-- running script %s (%d lines)" % (path, len(lines)))
        return await self.run(lines, strict=strict)

    # -- informational commands --------------------------------------------

    async def cmd_help(self, topic: str = "") -> None:
        if topic:
            doc = getattr(self, "cmd_" + topic.replace("-", "_"), None)
            self.print(doc.__doc__.strip() if doc and doc.__doc__
                       else "no help for %r" % topic)
            return
        self.print(HELP)

    async def cmd_info(self, *_args: str) -> None:
        """Show backend, PVT corner, clock and the current configuration."""
        self.print(self.chip.describe())

    cmd_pvt = cmd_info

    async def cmd_pins(self, *_args: str) -> None:
        """Show every pin value, the readout pointer and sim time."""
        self.print(self.chip.pin_report())

    async def cmd_status(self, *_args: str) -> None:
        """Read all 16 status bytes and decode them (does not freeze first)."""
        st = await self.chip.read_status()
        self.last_status = st
        self.print(st.table())

    # -- pin-level commands -------------------------------------------------

    async def cmd_ui(self, value: str) -> None:
        """Drive the dedicated inputs:  ui <value>   (0x80, 128, 0b1000_0000)."""
        self.chip.ui_in = parse_int(value)
        self.print("ui_in = 0x%02X" % self.chip.ui_in)

    async def cmd_uio(self, value: str) -> None:
        """Drive the bidirectional inputs (config phase only):  uio <value>."""
        self.chip.uio_in = parse_int(value)
        self.print("uio_in = 0x%02X" % self.chip.uio_in)

    async def cmd_rst(self, value: str) -> None:
        """Drive reset:  rst 0|1   (0 = asserted/reset)."""
        self.chip.rst_n = parse_int(value)
        self.print("rst_n = %d" % self.chip.rst_n)

    async def cmd_ena(self, value: str) -> None:
        """Drive the Tiny Tapeout enable pin:  ena 0|1."""
        self.chip.ena = parse_int(value)
        self.print("ena = %d" % self.chip.ena)

    async def cmd_clk(self, value: str) -> None:
        """Drive the clock level and hold a half period:  clk 0|1."""
        level = parse_int(value) & 1
        await self.chip.half(level)
        self.print("clk = %d (t=%.3f ns)" % (level, self.chip.time_ns))

    async def cmd_tick(self, n: str = "1") -> None:
        """Step n complete clock cycles (default 1):  tick [n] / step [n]."""
        count = parse_int(n)
        await self.chip.tick(count)
        self.print("stepped %d cycle(s), t=%.3f ns" % (count, self.chip.time_ns))

    cmd_step = cmd_tick

    async def cmd_period(self, value: str) -> None:
        """Set the clock period in ns:  period 20  (50 MHz)."""
        self.chip.period_ns = float(value)
        self.print("period = %.4g ns -> %.3f MHz, high %.4g ns" % (
            self.chip.period_ns, self.chip.freq_mhz, self.chip.t_high_ns))

    async def cmd_duty(self, value: str) -> None:
        """Set the clock duty cycle:  duty 0.5  (the capture aperture is high time)."""
        self.chip.duty = float(value)
        self.print("duty = %.4g -> high %.4g ns" % (
            self.chip.duty, self.chip.t_high_ns))

    # -- protocol-level commands -------------------------------------------

    async def cmd_config(self, *args: str) -> None:
        """Reset and commit a configuration.

        config 0x4DFF                       raw 16-bit word
        config seg=3333 pat=worst cansel=1  named fields
        config show                         show the committed word
        """
        if not args or args[0] == "show":
            if self.chip.last_config is None:
                self.print("no configuration committed yet")
            else:
                c = self.chip.last_config
                self.print("word 0x%04X seg=%s pat=%s cansel=%d winsel=%d "
                           "window=%d cyc force_can=%d force_err=%d" % (
                               c["word"], "".join(str(s) for s in c["seg"]),
                               c["pattern"], c["cansel"], c["winsel"],
                               c["window_cycles"], c["force_can"],
                               c["force_err"]))
            return
        if len(args) == 1 and "=" not in args[0]:
            word = await self.chip.configure(parse_int(args[0]))
        else:
            kwargs: Dict[str, Any] = {}
            for arg in args:
                if "=" not in arg:
                    raise ReplError("expected key=value, got %r" % arg)
                key, value = arg.split("=", 1)
                key = key.strip().lower()
                if key in ("seg", "segs", "pat", "pattern"):
                    kwargs["seg" if key in ("seg", "segs") else "pat"] = value
                elif key in ("cansel", "winsel", "force_can", "force_err",
                             "settle", "boot_cycles"):
                    kwargs[key] = parse_int(value)
                else:
                    raise ReplError("unknown configuration field %r" % key)
            word = await self.chip.configure(**kwargs)
        self.print("committed 0x%04X: %s" % (word, decode_config(word)))

    cmd_boot = cmd_config

    async def cmd_run(self, ops: str = "1") -> None:
        """Advance n measured operations (n x 19 cycles):  run 100."""
        count = parse_int(ops)
        await self.chip.run_ops(count)
        self.print("ran %d frame(s) = %d cycles, t=%.3f ns" % (
            count, count * FRAME_CYCLES, self.chip.time_ns))

    async def cmd_cycles(self, n: str) -> None:
        """Advance n raw clock cycles:  cycles 37."""
        count = parse_int(n)
        await self.chip.tick(count)
        self.print("ran %d cycle(s), t=%.3f ns" % (count, self.chip.time_ns))

    async def cmd_freeze(self, value: str) -> None:
        """Assert/release FREEZE (ui_in[7]):  freeze 1."""
        on = bool(parse_int(value))
        await self.chip.set_freeze(on)
        self.print("freeze = %s (ui_in=0x%02X)" % (on, self.chip.ui_in))

    def _current_config(self) -> Dict[str, Any]:
        """Reuse the committed configuration when one exists."""
        if self.chip.last_config is None:
            return {}
        return {"word": self.chip.last_config["word"]}

    async def cmd_measure(self, ops: str = "20") -> None:
        """configure + run + freeze + read in one go:  measure 50."""
        count = parse_int(ops)
        st = await self.chip.measure(count, **self._current_config())
        self.last_status = st
        self.print(st.table())

    # -- experiments --------------------------------------------------------

    async def cmd_sweep(self, *args: str) -> None:
        """Scan clock periods:  sweep <pmin_ns> <pmax_ns> [steps] [ops]."""
        if len(args) < 2:
            raise ReplError("usage: sweep <pmin_ns> <pmax_ns> [steps] [ops]")
        pmin, pmax = float(args[0]), float(args[1])
        steps = parse_int(args[2]) if len(args) > 2 else 9
        ops = parse_int(args[3]) if len(args) > 3 else 20
        if not 0 < pmin < pmax:
            raise ReplError("need 0 < pmin < pmax")
        periods = [pmin + (pmax - pmin) * i / max(steps - 1, 1)
                   for i in range(steps)]
        self.print("  %10s %10s %10s %8s %8s" % (
            "period_ns", "freq_MHz", "high_ns", "ops", "err"))
        results = []
        for period in periods:
            self.chip.period_ns = period
            st = await self.chip.measure(ops, **self._current_config())
            results.append((period, st))
            self.print("  %10.4f %10.3f %10.4f %8d %8d" % (
                period, st.freq_mhz, st.high_time_ns, st.ops, st.err_cnt))
        self.last_sweep = results
        self.last_status = results[-1][1]
        failing = [p for p, st in results if st.err_cnt > 0]
        if failing:
            self.print("  first failing period in scan: %.4f ns (%.3f MHz)"
                       % (min(failing), 1e3 / min(failing)))
        else:
            self.print("  no failure in the scanned range")

    async def cmd_findfail(self, *args: str) -> None:
        """Bisect the first-failing period:  findfail <p_fail> <p_pass> [ops] [tol]."""
        if len(args) < 2:
            raise ReplError("usage: findfail <p_fail_ns> <p_pass_ns> [ops] [tol_ns]")
        p_fail, p_pass = float(args[0]), float(args[1])
        ops = parse_int(args[2]) if len(args) > 2 else 20
        tol = float(args[3]) if len(args) > 3 else 0.25
        p_pass_found, p_fail_found, _trace = await self.chip.find_failure_period(
            p_fail, p_pass, ops=ops, tol_ns=tol, **self._current_config())
        if p_pass_found is None:
            self.print("  no boundary found in (%.4f, %.4f) ns" % (p_fail, p_pass))
        else:
            self.print("  boundary: fails at %.4f ns, passes at %.4f ns "
                       "-> f_fail ~ %.3f MHz"
                       % (p_fail_found, p_pass_found, 1e3 / p_pass_found))

    async def cmd_script(self, path: str) -> None:
        """Run commands from a file:  script examples/pin_level.txt."""
        if not os.path.isfile(path):
            raise ReplError("script not found: %s" % path)
        with open(path) as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                self.print("  >>> %s" % line.strip())
                try:
                    if not await self.execute(line):
                        return
                except (ReplError, ChipError) as exc:
                    raise ReplError("script %s line %d: %s" % (path, lineno, exc))

    async def cmd_assert(self, *expr: str) -> None:
        """Assert a Python expression over the last status:  assert st.err_cnt == 0."""
        if not expr:
            raise ReplError("usage: assert <expression>")
        text = " ".join(expr)
        st = self.last_status
        scope = {
            "chip": self.chip, "st": st, "status": st,
            "period": self.chip.period_ns, "ops": st.ops if st else None,
            "sweep": self.last_sweep,
            "float": float, "int": int, "abs": abs, "min": min, "max": max,
            "round": round, "len": len,
        }
        try:
            value = eval(text, {"__builtins__": {}}, scope)  # noqa: S307
        except Exception as exc:
            raise ReplError("cannot evaluate %r: %s" % (text, exc))
        if not value:
            raise ReplError("assertion failed: %s" % text)
        self.print("  ok: %s" % text)

    async def cmd_echo(self, *text: str) -> None:
        """Print a line:  echo hello."""
        self.print(" ".join(text))

    async def cmd_quit(self, *_args: str) -> None:
        """Leave the emulator."""
        self.print("bye")

    cmd_exit = cmd_quit


HELP = """\
pin level
  ui <v>            drive ui_in (0x80, 128, 0b1000_0000)
  uio <v>           drive uio_in (config phase only)
  rst <0|1>         drive rst_n (0 = reset asserted)
  ena <0|1>         drive the Tiny Tapeout enable pin
  clk <0|1>         drive clk level, hold a half period
  tick [n] / step   step n complete clock cycles (default 1)
  pins              show every pin, the readout pointer and sim time
  period <ns>       set the clock period (period 20 -> 50 MHz)
  duty <frac>       set the clock duty cycle (high time is the aperture)

protocol level
  config <word>              reset + commit a raw 16-bit word
  config key=value ...       seg=3333 pat=worst cansel=1 winsel=0 force_err=1
  config show                show the committed word
  run <ops>                  advance ops measured operations (19 cycles each)
  cycles <n>                 advance n raw clock cycles
  freeze <0|1>               drive FREEZE (ui_in[7])
  status                     read + decode the 16 status bytes
  measure [ops]              configure + run + freeze + read

experiments and scripts
  sweep <pmin> <pmax> [steps] [ops]     scan clock periods
  findfail <p_fail> <p_pass> [ops] [tol]  bisect the first-failing period
  script <file>             run a command script
  assert <expr>             assert over the last status (st, chip, sweep)
  echo <text>               print a line
  info / pvt                show backend, corner, clock, configuration
  help [cmd]                this list, or one command's help
  quit / exit               leave the emulator
"""
