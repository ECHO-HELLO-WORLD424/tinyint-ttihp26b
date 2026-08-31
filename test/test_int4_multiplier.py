# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.triggers import Timer


def signed_int4(value):
    """Interpret a four-bit value as a Python two's-complement integer."""
    return value - 16 if value & 0x8 else value


async def check_all_operands(dut, signed_mode):
    dut.ena.value = 1
    dut.clk.value = 0
    dut.rst_n.value = 1
    dut.uio_in.value = signed_mode << 4

    for multiplier in range(16):
        for multiplicand in range(16):
            dut.ui_in.value = (multiplier << 4) | multiplicand
            await Timer(1, unit="ns")

            if signed_mode:
                expected = (
                    signed_int4(multiplier) * signed_int4(multiplicand)
                ) & 0xFF
            else:
                expected = multiplier * multiplicand

            actual = int(dut.uo_out.value)
            assert actual == expected, (
                f"mode={'signed' if signed_mode else 'unsigned'}, "
                f"multiplier=0x{multiplier:x}, multiplicand=0x{multiplicand:x}: "
                f"expected 0x{expected:02x}, got 0x{actual:02x}"
            )

            assert int(dut.uio_out.value) == 0
            assert int(dut.uio_oe.value) == 0


@cocotb.test()
async def test_all_unsigned_products(dut):
    """Exhaustively test all 256 unsigned INT4 operand combinations."""
    await check_all_operands(dut, signed_mode=0)


@cocotb.test()
async def test_all_signed_products(dut):
    """Exhaustively test all 256 signed INT4 operand combinations."""
    await check_all_operands(dut, signed_mode=1)
