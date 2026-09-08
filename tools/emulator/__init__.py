# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Interactive cocotb emulator for the tt_um_echoworld424_tpv test chip.

The package is split so that host-side commands never import cocotb:

  pvt.py        PVT corner table (voltage / temperature / corner name)
  artifacts.py  locate + prepare the post-route netlist and per-corner SDF
  chip.py       TpvChip: pin-level and protocol-level cocotb driver
  scenarios.py  ready-made experiments (hello, pins, pvtsweep, selftest, ...)
  repl.py       interactive command loop
  session.py    the cocotb test module that dispatches on +scenario=

Public entry point: ``python3 tools/chip_emulate.py --help``.
"""

from .pvt import CORNERS, PVT, corner_names, get_corner  # noqa: F401

__all__ = ["PVT", "CORNERS", "get_corner", "corner_names"]
