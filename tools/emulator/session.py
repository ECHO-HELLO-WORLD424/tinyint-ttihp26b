# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""cocotb test module that hosts the chip emulator.

The launcher (``tools/chip_emulate.py``) builds the simulation and then runs
this module with plusargs:

    +scenario=<hello|pins|patterns|dft|pvtsweep|selftest|repl>
    +backend=<rtl|sdf>     +corner=<corner name>
    +period=<ns>           +duty=<0..1>        +ops=<n>
    +script=<file>         (scenario=repl)
    +sdf=<file>            (testbench SDF annotation)
    +netlist_source=..., +sdf_source=..., +netlist_sha256=..., +sdf_sha256=...

A scenario that returns non-zero fails the cocotb test, so ``results.xml`` and
the launcher exit status reflect the outcome.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import cocotb

from .chip import TpvChip
from .pvt import get_corner
from .repl import Repl
from .scenarios import SCENARIOS


def _opt(opts: Dict[str, Any], key: str, default: Optional[str] = None) -> Optional[str]:
    value = opts.get(key, default)
    if value is True or value is None:
        return default
    return str(value)


def _header(opts: Dict[str, Any], chip: TpvChip) -> str:
    lines = [
        "",
        "=" * 78,
        " tt_um_echoworld424_tpv chip emulator",
        "=" * 78,
        chip.describe(),
    ]
    for label, key in (("netlist", "netlist_source"), ("sdf", "sdf_source")):
        src = _opt(opts, key)
        if src:
            sha = _opt(opts, key.replace("_source", "_sha256"), "") or ""
            lines.append("%-7s : %s%s" % (label, src, ("  sha256 " + sha) if sha else ""))
    lines.append("=" * 78)
    return "\n".join(lines)


@cocotb.test()
async def emulate(dut):
    """Entry point: build a chip model, then run one scenario."""
    opts: Dict[str, Any] = dict(cocotb.plusargs)
    scenario = (_opt(opts, "scenario", "hello") or "hello").lower()
    backend = (_opt(opts, "backend", "rtl") or "rtl").lower()
    corner_name = _opt(opts, "corner")
    pvt = get_corner(corner_name) if corner_name else None
    if backend == "sdf" and pvt is None:
        pvt = get_corner(None)

    chip = TpvChip(
        dut,
        pvt=pvt,
        backend=backend,
        period_ns=float(_opt(opts, "period", "100") or 100),
        duty=float(_opt(opts, "duty", "0.5") or 0.5),
    )
    print(_header(opts, chip), flush=True)

    if scenario == "repl":
        repl = Repl(chip)
        script = _opt(opts, "script")
        if script:
            rc = await repl.run_file(script)
        else:
            rc = await repl.run()
    else:
        try:
            handler = SCENARIOS[scenario]
        except KeyError:
            raise AssertionError(
                "unknown scenario %r; available: %s"
                % (scenario, ", ".join(sorted(SCENARIOS) + ["repl"])))
        rc = await handler(chip, opts)

    if rc:
        raise AssertionError("scenario %r reported %d failed check(s)"
                             % (scenario, rc))
    print("\nscenario %r finished cleanly at t=%.1f ns" % (
        scenario, chip.time_ns), flush=True)
