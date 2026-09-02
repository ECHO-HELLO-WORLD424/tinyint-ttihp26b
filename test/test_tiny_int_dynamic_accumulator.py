# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


WIDTH = 20
MASK = (1 << WIDTH) - 1
MODE_TO_BOUNDARY = {0b01: 8, 0b10: 12, 0b11: 16}


def extended_product(raw_product, signed_mode):
    if signed_mode and raw_product & 0x80:
        return raw_product | 0xFFF00
    return raw_product


def expected_stage_enable(state, addend, mode, accumulate=True):
    if not accumulate:
        return 0

    boundary = MODE_TO_BOUNDARY[mode]
    active_stages = boundary // 4
    enables = (1 << active_stages) - 1
    low_mask = (1 << boundary) - 1
    low_carry = ((state & low_mask) + (addend & low_mask)) >> boundary
    negative = bool(addend & (1 << 19))
    delta = (low_carry - 1) if negative else low_carry

    if delta == 0:
        return enables

    for stage in range(active_stages, 5):
        enables |= 1 << stage
        nibble = (state >> (4 * stage)) & 0xF
        if delta > 0 and nibble != 0xF:
            break
        if delta < 0 and nibble != 0x0:
            break
    return enables


def drive(
    dut,
    *,
    clear=0,
    load=0,
    accumulate=0,
    signed_mode=0,
    mode=0b01,
    load_value=0,
    addend=0,
):
    dut.dynamic_clear.value = clear
    dut.dynamic_load.value = load
    dut.dynamic_accumulate.value = accumulate
    dut.dynamic_signed_mode.value = signed_mode
    dut.dynamic_accumulator_mode.value = mode
    dut.dynamic_load_value.value = load_value
    dut.dynamic_addend.value = addend


async def start_and_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    # Initialize the other independent leaf controls to prevent X propagation.
    dut.accumulator_clear.value = 0
    dut.accumulator_load.value = 0
    dut.accumulator_accumulate.value = 0
    dut.accumulator_signed_mode.value = 0
    dut.accumulator_load_value.value = 0
    dut.accumulator_addend.value = 0
    drive(dut)
    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    assert int(dut.dynamic_accumulator_value.value) == 0
    assert int(dut.dynamic_accumulator_overflow.value) == 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


async def clock_drive(dut, **kwargs):
    drive(dut, **kwargs)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


async def load_state(dut, state, mode, signed_mode=0):
    await clock_drive(
        dut,
        load=1,
        load_value=state,
        mode=mode,
        signed_mode=signed_mode,
    )
    assert int(dut.dynamic_accumulator_value.value) == state


@cocotb.test()
async def test_dynamic_reset_hold_and_control_priority(dut):
    """Reset, hold, clear, and load priority apply to every stage."""
    await start_and_reset(dut)

    for mode in MODE_TO_BOUNDARY:
        await load_state(dut, 0xABCDE, mode)
        for addend in (0, 1, 0xFF, 0xFFF80):
            await clock_drive(dut, mode=mode, addend=addend)
            assert int(dut.dynamic_accumulator_value.value) == 0xABCDE

        await clock_drive(
            dut,
            clear=1,
            load=1,
            accumulate=1,
            mode=mode,
            load_value=0x12345,
            addend=0xFF,
        )
        assert int(dut.dynamic_accumulator_value.value) == 0

        await clock_drive(
            dut,
            load=1,
            accumulate=1,
            mode=mode,
            load_value=0x54321,
            addend=0xFF,
        )
        assert int(dut.dynamic_accumulator_value.value) == 0x54321

    # Verify asynchronous reset between edges reaches all independently
    # enabled state elements.
    await Timer(2, unit="ns")
    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    assert int(dut.dynamic_accumulator_value.value) == 0
    assert int(dut.dynamic_accumulator_overflow.value) == 0


@cocotb.test()
async def test_dynamic_directed_boundary_and_cascade_events(dut):
    """Exercise hold, carry, borrow, and every cold-nibble cascade depth."""
    await start_and_reset(dut)

    cases = (
        # mode, state, raw product, signed, result, enabled-stage mask
        (0b01, 0x54320, 0x01, 0, 0x54321, 0b00011),  # no crossing
        (0b01, 0x543FF, 0x01, 0, 0x54400, 0b00111),  # one cold stage
        (0b01, 0x54FFF, 0x01, 0, 0x55000, 0b01111),  # two cold stages
        (0b01, 0xFFFFF, 0x01, 0, 0x00000, 0b11111),  # full carry cascade
        (0b01, 0x54300, 0xFF, 1, 0x542FF, 0b00111),  # signed borrow
        (0b01, 0x54000, 0xFF, 1, 0x53FFF, 0b01111),  # borrow two stages
        (0b01, 0x00000, 0xFF, 1, 0xFFFFF, 0b11111),  # full borrow
        (0b10, 0x54FFF, 0x01, 0, 0x55000, 0b01111),
        (0b10, 0x5FFFF, 0x01, 0, 0x60000, 0b11111),
        (0b10, 0x54000, 0xFF, 1, 0x53FFF, 0b01111),
        (0b10, 0x00000, 0xFF, 1, 0xFFFFF, 0b11111),
        (0b11, 0x5FFFF, 0x01, 0, 0x60000, 0b11111),
        (0b11, 0x50000, 0xFF, 1, 0x4FFFF, 0b11111),
        (0b11, 0x00000, 0xFF, 1, 0xFFFFF, 0b11111),
    )

    for mode, state, raw, signed_mode, expected, enable_mask in cases:
        addend = extended_product(raw, signed_mode)
        await load_state(dut, state, mode, signed_mode)
        drive(
            dut,
            accumulate=1,
            signed_mode=signed_mode,
            mode=mode,
            addend=addend,
        )
        await Timer(1, unit="ns")
        assert int(dut.dynamic_addition_result.value) == expected
        assert int(dut.dynamic_stage_write_enable.value) == enable_mask
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        assert int(dut.dynamic_accumulator_value.value) == expected


@cocotb.test()
async def test_dynamic_all_products_at_representative_states(dut):
    """Check every raw product/sign interpretation at boundary edge states."""
    await start_and_reset(dut)

    states = (
        0x00000,
        0x00001,
        0x0007F,
        0x00080,
        0x000FF,
        0x00F00,
        0x00FFF,
        0x0F000,
        0x0FFFF,
        0x7FFFF,
        0x80000,
        0xF0000,
        0xFFFFF,
        0xA5A5A,
        0x5A5A5,
    )

    for mode in MODE_TO_BOUNDARY:
        for state in states:
            await load_state(dut, state, mode)
            for signed_mode in (0, 1):
                for raw_product in range(256):
                    addend = extended_product(raw_product, signed_mode)
                    full_sum = state + addend
                    expected = full_sum & MASK
                    expected_carry = (full_sum >> WIDTH) & 1
                    expected_signed_overflow = (
                        ((state >> 19) & 1) == ((addend >> 19) & 1)
                        and ((expected >> 19) & 1) != ((state >> 19) & 1)
                    )
                    drive(
                        dut,
                        accumulate=0,
                        signed_mode=signed_mode,
                        mode=mode,
                        addend=addend,
                    )
                    await Timer(1, unit="ns")
                    assert int(dut.dynamic_addition_result.value) == expected
                    assert int(dut.dynamic_addition_carry.value) == expected_carry
                    assert int(dut.dynamic_addition_overflow.value) == (
                        expected_signed_overflow
                        if signed_mode
                        else expected_carry
                    )
                    assert int(dut.dynamic_stage_write_enable.value) == 0


@cocotb.test()
async def test_dynamic_randomized_streams_and_sticky_overflow(dut):
    """Compare long back-to-back streams in all modes with a Python model."""
    await start_and_reset(dut)
    rng = random.Random(0xD1AACC)

    for mode in MODE_TO_BOUNDARY:
        for signed_mode in (0, 1):
            state = rng.randrange(1 << WIDTH)
            sticky = 0
            await load_state(dut, state, mode, signed_mode)

            for cycle in range(10_000):
                raw_product = rng.randrange(256)
                addend = extended_product(raw_product, signed_mode)
                full_sum = state + addend
                expected = full_sum & MASK
                carry = (full_sum >> WIDTH) & 1
                signed_overflow = (
                    ((state >> 19) & 1) == ((addend >> 19) & 1)
                    and ((expected >> 19) & 1) != ((state >> 19) & 1)
                )
                overflow = signed_overflow if signed_mode else carry
                enable_mask = expected_stage_enable(state, addend, mode)

                drive(
                    dut,
                    accumulate=1,
                    signed_mode=signed_mode,
                    mode=mode,
                    addend=addend,
                )
                await Timer(1, unit="ns")
                assert int(dut.dynamic_addition_result.value) == expected
                assert int(dut.dynamic_addition_carry.value) == carry
                assert int(dut.dynamic_addition_overflow.value) == overflow
                assert int(dut.dynamic_stage_write_enable.value) == enable_mask
                await RisingEdge(dut.clk)
                await Timer(1, unit="ns")

                state = expected
                sticky |= overflow
                assert int(dut.dynamic_accumulator_value.value) == state, (
                    f"mode={mode:02b} signed={signed_mode} cycle={cycle}"
                )
                assert int(dut.dynamic_accumulator_overflow.value) == sticky
