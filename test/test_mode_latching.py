# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


COMMAND_CLEAR = 0b001
COMMAND_MAC_LAST = 0b011
COMMAND_READ = 0b100


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


async def accept_mac_last(dut, packed_operands, live_signed_mode):
    dut.ui_in.value = packed_operands
    dut.uio_in.value = control_value(
        command=COMMAND_MAC_LAST, signed_mode=live_signed_mode, valid=1
    )
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.uio_in.value = control_value(signed_mode=live_signed_mode)


async def read_low_byte(dut, live_signed_mode):
    dut.ui_in.value = 0
    dut.uio_in.value = control_value(
        command=COMMAND_READ, signed_mode=live_signed_mode, valid=1
    )
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    # Exactly one valid cycle per READ, as in the released protocol.
    dut.uio_in.value = control_value(signed_mode=live_signed_mode)
    # P3 protocol: the response byte is emitted two cycles after acceptance.
    for _ in range(6):
        if (int(dut.uio_out.value) >> 6) & 1:
            break
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
    else:
        raise AssertionError("READ response_valid did not assert within 6 cycles")
    result = int(dut.uo_out.value)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert ((int(dut.uio_out.value) >> 6) & 1) == 0
    return result


@cocotb.test()
async def test_mode_changes_only_on_accepted_clear(dut):
    """The live mode pin must not alter arithmetic inside a transaction."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    # Reset establishes unsigned mode. The live high mode pin must not turn
    # 0xf * 0x2 into a signed product without an accepted CLEAR.
    await accept_mac_last(dut, packed_operands=0xF2, live_signed_mode=1)
    assert await read_low_byte(dut, live_signed_mode=1) == 30

    # An accepted signed CLEAR changes the core-owned mode. Toggling the live
    # pin back low before the MAC must not change the latched signed mode.
    await accept_clear(dut, signed_mode=1)
    await accept_mac_last(dut, packed_operands=0xF2, live_signed_mode=0)
    assert await read_low_byte(dut, live_signed_mode=0) == 0xFE

    # It changes only after another accepted CLEAR.
    await accept_clear(dut, signed_mode=0)
    await accept_mac_last(dut, packed_operands=0xF2, live_signed_mode=1)
    assert await read_low_byte(dut, live_signed_mode=1) == 30

    assert int(dut.uio_oe.value) == 0xE0
    assert (int(dut.uio_out.value) & 0x1F) == 0
