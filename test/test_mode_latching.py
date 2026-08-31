# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


COMMAND_CLEAR = 0b001


def control_value(*, command=0, signed_mode=0, valid=0):
    return (signed_mode << 4) | (command << 1) | valid


async def reset(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def accept_clear(dut, signed_mode):
    dut.uio_in.value = control_value(
        command=COMMAND_CLEAR, signed_mode=signed_mode, valid=1
    )
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.uio_in.value = control_value(signed_mode=signed_mode)
    await Timer(1, unit="ns")


@cocotb.test()
async def test_mode_changes_only_on_accepted_clear(dut):
    """The live mode pin must not alter arithmetic inside a transaction."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    # Reset establishes unsigned mode. 0xf * 0x2 is 30 unsigned.
    dut.ui_in.value = 0xF2
    dut.uio_in.value = control_value(signed_mode=1)
    await Timer(1, unit="ns")
    assert int(dut.uo_out.value) == 30

    # An accepted signed CLEAR changes the core-owned mode. 0xf is now -1.
    await accept_clear(dut, signed_mode=1)
    dut.ui_in.value = 0xF2
    await Timer(1, unit="ns")
    assert int(dut.uo_out.value) == 0xFE

    # Toggling the live pin back low does not change the latched signed mode.
    dut.uio_in.value = control_value(signed_mode=0)
    await Timer(1, unit="ns")
    assert int(dut.uo_out.value) == 0xFE

    # It changes only after another accepted CLEAR.
    await accept_clear(dut, signed_mode=0)
    dut.ui_in.value = 0xF2
    await Timer(1, unit="ns")
    assert int(dut.uo_out.value) == 30

    assert int(dut.uio_oe.value) == 0xE0
    assert (int(dut.uio_out.value) & 0x1F) == 0
