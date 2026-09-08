# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Example: write your own cocotb test against the emulator driver.

Run it with the same build/launcher as the built-in scenarios::

    python3 tools/chip_emulate.py run hello --module emulator.example_custom_test \
        --backend sdf --corner slow

(``--module`` replaces the test module; the backend/corner/SDF plumbing is
unchanged.  The ``run`` subcommand only uses its scenario name when the
default module is in use.)

The driver is also usable from a plain cocotb testbench::

    from emulator.chip import TpvChip

    @cocotb.test()
    async def my_test(dut):
        chip = TpvChip(dut, period_ns=20.0)          # 50 MHz, RTL backend
        st = await chip.measure(100, seg="3333", pat="worst")
        assert st.err_cnt == 0
"""

from __future__ import annotations

import cocotb

from .chip import TpvChip, config_word
from .pvt import get_corner


@cocotb.test()
async def worst_case_carry_is_error_free_at_10_mhz(dut):
    """The predeclared measurement config at the submitted clock."""
    corner = get_corner(cocotb.plusargs.get("corner"))
    chip = TpvChip(dut, pvt=corner, backend=str(cocotb.plusargs.get("backend", "rtl")),
                   period_ns=100.0)                  # 10 MHz, 50 ns high time
    st = await chip.measure(50, seg="3333", pat="worst", cansel=3, winsel=0)
    print(st.table(), flush=True)
    assert st.ops == 50
    assert st.err_cnt == 0, "functional failure at the submitted clock"


@cocotb.test()
async def pin_level_protocol(dut):
    """Drive the pins by hand instead of using the protocol helpers."""
    chip = TpvChip(dut, backend=str(cocotb.plusargs.get("backend", "rtl")),
                   period_ns=100.0)
    word = config_word(seg="1111", pat="prbs", cansel=1, winsel=0,
                       force_can=chip.force_can_default)

    chip.clk = 0
    chip.rst_n = 0
    chip.ui_in = word & 0xFF
    chip.uio_in = (word >> 8) & 0xFF
    await chip.tick(4)
    assert chip.uio_oe == 0x00, "uio must be an input while in reset"

    chip.rst_n = 1
    await chip.tick(3)
    assert chip.uio_oe == 0xFF, "uio must switch to the status output"
    chip.ui_in = 0x00
    chip.uio_in = 0x00

    strobes = 0
    for _ in range(2 * 19):
        await chip.tick()
        strobes += chip.pins()["frame_strobe"] or 0
    assert strobes == 2, "one frame strobe every 19 cycles"

    await chip.set_freeze(True)
    st = await chip.read_status()
    assert st.cfg_echo == 0x55          # seg3..seg0 = 1,1,1,1
    print(st.table(), flush=True)
