# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


ACCUMULATOR_MASK = (1 << 20) - 1
COMMAND_CLEAR = 0b001


def signed_int4(value):
    """Interpret a four-bit value as a Python two's-complement integer."""
    return value - 16 if value & 0x8 else value


def control_value(*, command=0, signed_mode=0, valid=0):
    return (signed_mode << 4) | (command << 1) | valid


async def check_all_products(dut, signed_mode):
    dut.extender_signed_mode.value = signed_mode

    for product in range(256):
        dut.extender_product.value = product
        await Timer(1, unit="ns")

        if signed_mode and product & 0x80:
            expected = (product - 256) & ACCUMULATOR_MASK
        else:
            expected = product

        actual = int(dut.extender_extended_product.value)
        assert actual == expected, (
            f"mode={'signed' if signed_mode else 'unsigned'}, "
            f"product=0x{product:02x}: expected 0x{expected:05x}, "
            f"got 0x{actual:05x}"
        )


@cocotb.test()
async def test_all_unsigned_product_extensions(dut):
    """Zero-extend every possible raw product to 20 bits."""
    await check_all_products(dut, signed_mode=0)


@cocotb.test()
async def test_all_signed_product_extensions(dut):
    """Sign-extend every possible raw product to 20 bits."""
    await check_all_products(dut, signed_mode=1)


@cocotb.test()
async def test_multiplier_to_extender_integration(dut):
    """The core must extend the multiplier output using its active mode."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    for signed_mode in (0, 1):
        dut.uio_in.value = control_value(
            command=COMMAND_CLEAR, signed_mode=signed_mode, valid=1
        )
        await RisingEdge(dut.clk)
        dut.uio_in.value = control_value(signed_mode=signed_mode)

        for multiplier in range(16):
            for multiplicand in range(16):
                dut.ui_in.value = (multiplier << 4) | multiplicand
                await Timer(1, unit="ns")

                if signed_mode:
                    expected = (
                        signed_int4(multiplier) * signed_int4(multiplicand)
                    ) & ACCUMULATOR_MASK
                else:
                    expected = multiplier * multiplicand

                actual = int(dut.integrated_extended_product.value)
                assert actual == expected, (
                    f"mode={'signed' if signed_mode else 'unsigned'}, "
                    f"multiplier=0x{multiplier:x}, "
                    f"multiplicand=0x{multiplicand:x}: "
                    f"expected 0x{expected:05x}, got 0x{actual:05x}"
                )
