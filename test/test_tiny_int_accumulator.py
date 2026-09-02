# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer


ACCUMULATOR_WIDTH = 20
ACCUMULATOR_MODULUS = 1 << ACCUMULATOR_WIDTH
ACCUMULATOR_MASK = ACCUMULATOR_MODULUS - 1
COMMAND_CLEAR = 0b001


def signed_int4(value):
    """Interpret a four-bit value as a Python two's-complement integer."""
    return value - 16 if value & 0x8 else value


def control_value(*, command=0, signed_mode=0, valid=0):
    return (signed_mode << 4) | (command << 1) | valid


def drive_controls(
    dut,
    *,
    clear=0,
    load=0,
    accumulate=0,
    signed_mode=0,
    load_value=0,
    addend=0,
):
    dut.accumulator_clear.value = clear
    dut.accumulator_load.value = load
    dut.accumulator_accumulate.value = accumulate
    dut.accumulator_signed_mode.value = signed_mode
    dut.accumulator_load_value.value = load_value
    dut.accumulator_addend.value = addend


async def start_and_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    drive_controls(dut)
    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    assert int(dut.accumulator_value.value) == 0
    assert int(dut.accumulator_overflow.value) == 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.accumulator_value.value) == 0
    assert int(dut.accumulator_overflow.value) == 0


async def clock_controls(dut, **controls):
    drive_controls(dut, **controls)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


@cocotb.test()
async def test_accumulator_reset_hold_and_async_reset(dut):
    """Reset clears immediately and disabled clocks preserve state."""
    await start_and_reset(dut)

    await clock_controls(dut, load=1, load_value=0x54321)
    assert int(dut.accumulator_value.value) == 0x54321

    for addend in (0, 1, 0x12345, ACCUMULATOR_MASK):
        await clock_controls(dut, addend=addend)
        assert int(dut.accumulator_value.value) == 0x54321

    # Assert reset between clock edges to verify the asynchronous reset path.
    await Timer(2, unit="ns")
    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    assert int(dut.accumulator_value.value) == 0
    assert int(dut.accumulator_overflow.value) == 0


@cocotb.test()
async def test_accumulator_control_priority(dut):
    """Clear wins over load, and load wins over accumulation."""
    await start_and_reset(dut)

    await clock_controls(dut, load=1, load_value=0x13579)
    assert int(dut.accumulator_value.value) == 0x13579

    await clock_controls(
        dut,
        clear=1,
        load=1,
        accumulate=1,
        load_value=0x2468A,
        addend=0x11111,
    )
    assert int(dut.accumulator_value.value) == 0

    await clock_controls(
        dut,
        load=1,
        accumulate=1,
        load_value=0xABCDE,
        addend=0x22222,
    )
    assert int(dut.accumulator_value.value) == 0xABCDE

    await clock_controls(dut, clear=1, addend=ACCUMULATOR_MASK)
    assert int(dut.accumulator_value.value) == 0


@cocotb.test()
async def test_accumulator_modulo_arithmetic_and_carry(dut):
    """The adder exposes carry and commits the wrapped 20-bit result."""
    await start_and_reset(dut)

    cases = (
        # initial value, addend, expected wrapped result, expected carry
        (0x00000, 0x00001, 0x00001, 0),
        (0x7FFFF, 0x00001, 0x80000, 0),
        (0xFFFF0, 0x00020, 0x00010, 1),
        (0xFFFFF, 0x00001, 0x00000, 1),
        (0x00000, 0xFFFFF, 0xFFFFF, 0),
        (0x00005, 0xFFFFD, 0x00002, 1),
    )

    for initial, addend, expected, expected_carry in cases:
        await clock_controls(dut, load=1, load_value=initial)
        drive_controls(dut, addend=addend)
        await Timer(1, unit="ns")
        assert int(dut.accumulator_addition_result.value) == expected
        assert int(dut.accumulator_addition_carry.value) == expected_carry

        await clock_controls(dut, accumulate=1, addend=addend)
        assert int(dut.accumulator_value.value) == expected


@cocotb.test()
async def test_accumulator_mode_dependent_sticky_overflow(dut):
    """Detect signed/unsigned overflow and retain it until clear or load."""
    await start_and_reset(dut)

    # Unsigned wrap sets overflow.
    await clock_controls(dut, load=1, load_value=ACCUMULATOR_MASK)
    drive_controls(dut, addend=1)
    await Timer(1, unit="ns")
    assert int(dut.accumulator_addition_overflow.value) == 1
    await clock_controls(dut, accumulate=1, addend=1)
    assert int(dut.accumulator_value.value) == 0
    assert int(dut.accumulator_overflow.value) == 1

    # The flag is sticky across non-overflowing additions and idle clocks.
    await clock_controls(dut, accumulate=1, addend=1)
    assert int(dut.accumulator_value.value) == 1
    assert int(dut.accumulator_overflow.value) == 1
    await clock_controls(dut)
    assert int(dut.accumulator_overflow.value) == 1

    # A load starts new accumulator state and clears the sticky flag.
    await clock_controls(dut, load=1, load_value=0x7FFFF)
    assert int(dut.accumulator_overflow.value) == 0

    # Signed positive overflow: 524287 + 1 cannot fit in signed 20 bits.
    drive_controls(dut, signed_mode=1, addend=1)
    await Timer(1, unit="ns")
    assert int(dut.accumulator_addition_carry.value) == 0
    assert int(dut.accumulator_addition_overflow.value) == 1
    await clock_controls(dut, accumulate=1, signed_mode=1, addend=1)
    assert int(dut.accumulator_value.value) == 0x80000
    assert int(dut.accumulator_overflow.value) == 1

    # Clear also starts new state and clears overflow.
    await clock_controls(dut, clear=1)
    assert int(dut.accumulator_overflow.value) == 0

    # Signed negative overflow: -524288 + -1 wraps to +524287.
    await clock_controls(dut, load=1, signed_mode=1, load_value=0x80000)
    await clock_controls(
        dut, accumulate=1, signed_mode=1, addend=ACCUMULATOR_MASK
    )
    assert int(dut.accumulator_value.value) == 0x7FFFF
    assert int(dut.accumulator_overflow.value) == 1

    # Signed -1 + 1 has an unsigned carry but no signed overflow.
    await clock_controls(
        dut, load=1, signed_mode=1, load_value=ACCUMULATOR_MASK
    )
    drive_controls(dut, signed_mode=1, addend=1)
    await Timer(1, unit="ns")
    assert int(dut.accumulator_addition_carry.value) == 1
    assert int(dut.accumulator_addition_overflow.value) == 0
    await clock_controls(dut, accumulate=1, signed_mode=1, addend=1)
    assert int(dut.accumulator_value.value) == 0
    assert int(dut.accumulator_overflow.value) == 0


@cocotb.test()
async def test_accumulator_back_to_back_throughput(dut):
    """One enabled add must commit on every consecutive rising edge."""
    await start_and_reset(dut)

    expected = 0
    addends = [1, 2, 3, 0xFFFFF, 0x40, 0xFF, 0xFFF80, 0xE1]
    for addend in addends * 32:
        expected = (expected + addend) & ACCUMULATOR_MASK
        await clock_controls(dut, accumulate=1, addend=addend)
        assert int(dut.accumulator_value.value) == expected


@cocotb.test()
async def test_core_datapath_reaches_accumulator_addition_input(dut):
    """Every product reaches only the enabled conventional adder."""
    await start_and_reset(dut)

    for signed_mode in (0, 1):
        dut.ui_in.value = 0
        dut.uio_in.value = control_value(
            command=COMMAND_CLEAR, signed_mode=signed_mode, valid=1
        )
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        dut.uio_in.value = control_value(
            command=0b010, signed_mode=1 - signed_mode, valid=1
        )

        for multiplier in range(16):
            for multiplicand in range(16):
                dut.ui_in.value = (multiplier << 4) | multiplicand
                await Timer(1, unit="ps")

                if signed_mode:
                    expected = (
                        signed_int4(multiplier) * signed_int4(multiplicand)
                    ) & ACCUMULATOR_MASK
                else:
                    expected = multiplier * multiplicand

                actual = int(
                    dut.integrated_accumulator_addition_result.value
                )
                assert actual == expected, (
                    f"mode={'signed' if signed_mode else 'unsigned'}, "
                    f"multiplier=0x{multiplier:x}, "
                    f"multiplicand=0x{multiplicand:x}: "
                    f"expected adder input 0x{expected:05x}, "
                    f"got 0x{actual:05x}"
                )
                assert int(dut.integrated_conventional_addend.value) == expected
                assert int(dut.integrated_dynamic_addend.value) == 0

        dut.uio_in.value = 0

    # The tight sub-nanosecond sweep deasserts valid before the next edge, so it
    # observes all 512 products without committing any of them.
    assert int(dut.integrated_accumulator_value.value) == 0


@cocotb.test()
async def test_accumulator_randomized_state_model(dut):
    """Compare 10,000 mixed control cycles against a software model."""
    await start_and_reset(dut)

    rng = random.Random(0x20ACCA)
    expected = 0
    expected_overflow_sticky = 0

    for cycle in range(10_000):
        clear = rng.randrange(16) == 0
        load = rng.randrange(8) == 0
        accumulate = bool(rng.getrandbits(1))
        signed_mode = bool(rng.getrandbits(1))
        load_value = rng.randrange(ACCUMULATOR_MODULUS)
        addend = rng.randrange(ACCUMULATOR_MODULUS)

        full_sum = expected + addend
        expected_sum = full_sum & ACCUMULATOR_MASK
        expected_carry = full_sum >> ACCUMULATOR_WIDTH
        expected_signed_overflow = (
            ((expected >> 19) & 1) == ((addend >> 19) & 1)
            and ((expected_sum >> 19) & 1) != ((expected >> 19) & 1)
        )
        expected_addition_overflow = (
            expected_signed_overflow if signed_mode else expected_carry
        )

        drive_controls(
            dut,
            clear=clear,
            load=load,
            accumulate=accumulate,
            signed_mode=signed_mode,
            load_value=load_value,
            addend=addend,
        )
        await Timer(1, unit="ns")
        assert int(dut.accumulator_addition_result.value) == expected_sum, (
            f"cycle {cycle}: combinational sum mismatch"
        )
        assert int(dut.accumulator_addition_carry.value) == expected_carry, (
            f"cycle {cycle}: carry mismatch"
        )
        assert (
            int(dut.accumulator_addition_overflow.value)
            == expected_addition_overflow
        ), f"cycle {cycle}: overflow event mismatch"

        if clear:
            expected = 0
            expected_overflow_sticky = 0
        elif load:
            expected = load_value
            expected_overflow_sticky = 0
        elif accumulate:
            expected = expected_sum
            expected_overflow_sticky |= expected_addition_overflow

        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        actual = int(dut.accumulator_value.value)
        assert actual == expected, (
            f"cycle {cycle}: expected accumulator 0x{expected:05x}, "
            f"got 0x{actual:05x}"
        )
        assert (
            int(dut.accumulator_overflow.value) == expected_overflow_sticky
        ), f"cycle {cycle}: sticky overflow mismatch"
