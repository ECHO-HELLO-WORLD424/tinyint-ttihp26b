# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer


MASK = (1 << 20) - 1
COMMAND_FINISH = 0b000
COMMAND_CLEAR = 0b001
COMMAND_MAC = 0b010
COMMAND_MAC_LAST = 0b011
COMMAND_READ = 0b100
SELECT_ACC_LOW = 0b000
SELECT_ACC_MIDDLE = 0b001
SELECT_ACC_HIGH = 0b010
SELECT_PAIR_COUNT = 0b011
SELECT_STATUS = 0b100
SELECT_LAST_PRODUCT = 0b101
SELECT_CONFIGURATION = 0b110
SELECT_DESIGN_ID = 0b111


def control_value(command=0, signed_mode=0, valid=0):
    return (signed_mode << 4) | (command << 1) | valid


def pack_operands(a, b):
    return ((a & 0xF) << 4) | (b & 0xF)


def int4(value):
    value &= 0xF
    return value - 16 if value & 8 else value


def product(a, b, signed_mode):
    if signed_mode:
        return int4(a) * int4(b)
    return (a & 0xF) * (b & 0xF)


async def reset(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)


async def issue(dut, command, data=0, signed_mode=0):
    dut.ui_in.value = data
    dut.uio_in.value = control_value(command, signed_mode, 1)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.uio_in.value = control_value(signed_mode=signed_mode)


async def read(dut, selector):
    await issue(dut, COMMAND_READ, selector)
    assert (int(dut.uio_out.value) >> 6) & 1
    return int(dut.uo_out.value)


async def read_accumulator(dut):
    low = await read(dut, SELECT_ACC_LOW)
    middle = await read(dut, SELECT_ACC_MIDDLE)
    high = await read(dut, SELECT_ACC_HIGH)
    return low | (middle << 8) | ((high & 0xF) << 16)


async def clear_config(dut, mode, signed_mode, zero_skip=0):
    payload = mode | (zero_skip << 2)
    await issue(dut, COMMAND_CLEAR, payload, signed_mode)


@cocotb.test()
async def test_core_configuration_and_new_read_selectors(dut):
    """Reset/defaults and every CLEAR configuration read back exactly."""
    await start(dut)

    assert await read(dut, SELECT_CONFIGURATION) == 0
    assert await read(dut, SELECT_DESIGN_ID) == 0x42

    for signed_mode in (0, 1):
        for zero_skip in (0, 1):
            for mode in range(4):
                await clear_config(dut, mode, signed_mode, zero_skip)
                expected = (zero_skip << 3) | (mode << 1) | signed_mode
                assert await read(dut, SELECT_CONFIGURATION) == expected
                assert int(dut.integrated_accumulator_mode.value) == mode
                assert int(dut.integrated_zero_skip.value) == zero_skip
                assert int(dut.integrated_conventional_accumulator_value.value) == 0
                assert int(dut.integrated_dynamic_accumulator_value.value) == 0

                # Live configuration pins cannot alter latched readback.
                dut.ui_in.value = 0xFF
                dut.uio_in.value = 0x10 if not signed_mode else 0
                await RisingEdge(dut.clk)
                dut.uio_in.value = 0
                assert await read(dut, SELECT_CONFIGURATION) == expected


@cocotb.test()
async def test_core_all_modes_are_bit_exact_for_matched_workloads(dut):
    """Replay adversarial and random workloads in all four architecture modes."""
    await start(dut)
    rng = random.Random(0xC0A5E)

    directed = [
        (-8, -8),
        (7, 7),
        (-8, 7),
        (7, -8),
        (-1, 1),
        (0, -8),
        (-8, 0),
    ] * 40

    for signed_mode in (0, 1):
        random_vectors = [
            (
                rng.randrange(-8, 8) if signed_mode else rng.randrange(16),
                rng.randrange(-8, 8) if signed_mode else rng.randrange(16),
            )
            for _ in range(1024)
        ]
        vectors = directed + random_vectors
        expected = sum(product(a, b, signed_mode) for a, b in vectors) & MASK

        reference = None
        for mode in range(4):
            await clear_config(dut, mode, signed_mode)
            dut.uio_in.value = control_value(COMMAND_MAC, 1 - signed_mode, 1)
            for a, b in vectors:
                dut.ui_in.value = pack_operands(a, b)
                await RisingEdge(dut.clk)
            await Timer(1, unit="ns")
            dut.uio_in.value = 0

            actual = await read_accumulator(dut)
            assert actual == expected
            if reference is None:
                reference = actual
            assert actual == reference
            assert await read(dut, SELECT_PAIR_COUNT) == 0xFF
            assert await read(dut, SELECT_STATUS) & 0x08


@cocotb.test()
async def test_core_operand_isolation_zero_skip_and_stage_enables(dut):
    """Only the selected datapath receives operands or a state write."""
    await start(dut)

    for mode in range(4):
        await clear_config(dut, mode, signed_mode=1)
        await FallingEdge(dut.clk)
        dut.ui_in.value = pack_operands(-3, 5)
        dut.uio_in.value = control_value(COMMAND_MAC, signed_mode=0, valid=1)
        await Timer(1, unit="ns")

        extended = (-15) & MASK
        if mode == 0:
            assert int(dut.integrated_conventional_accumulate.value) == 1
            assert int(dut.integrated_dynamic_accumulate.value) == 0
            assert int(dut.integrated_conventional_addend.value) == extended
            assert int(dut.integrated_dynamic_addend.value) == 0
        else:
            assert int(dut.integrated_conventional_accumulate.value) == 0
            assert int(dut.integrated_dynamic_accumulate.value) == 1
            assert int(dut.integrated_conventional_addend.value) == 0
            assert int(dut.integrated_dynamic_addend.value) == extended

        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        dut.uio_in.value = 0
        expected = extended
        assert int(dut.integrated_accumulator_value.value) == expected
        if mode == 0:
            assert int(dut.integrated_dynamic_accumulator_value.value) == 0
        else:
            assert int(dut.integrated_conventional_accumulator_value.value) == 0

    # A skipped zero is still an accepted pair and updates last_product/count,
    # but both data operands and state enables remain inactive.
    await clear_config(dut, 0b01, signed_mode=1, zero_skip=1)
    await FallingEdge(dut.clk)
    dut.ui_in.value = pack_operands(0, -8)
    dut.uio_in.value = control_value(COMMAND_MAC, valid=1)
    await Timer(1, unit="ns")
    assert int(dut.integrated_conventional_accumulate.value) == 0
    assert int(dut.integrated_dynamic_accumulate.value) == 0
    assert int(dut.integrated_conventional_addend.value) == 0
    assert int(dut.integrated_dynamic_addend.value) == 0
    assert int(dut.integrated_dynamic_stage_write_enable.value) == 0
    await RisingEdge(dut.clk)
    dut.uio_in.value = 0
    await Timer(1, unit="ns")
    assert await read(dut, SELECT_PAIR_COUNT) == 1
    assert await read(dut, SELECT_LAST_PRODUCT) == 0
    assert await read_accumulator(dut) == 0


@cocotb.test()
async def test_core_reserved_commands_and_done_rejection(dut):
    """All reserved commands and completed-state writes are rejected."""
    await start(dut)

    for reserved in (0b101, 0b110, 0b111):
        await clear_config(dut, 0b10, signed_mode=0)
        await issue(dut, COMMAND_MAC, pack_operands(15, 15))
        before = await read_accumulator(dut)
        before_count = await read(dut, SELECT_PAIR_COUNT)
        await issue(dut, reserved, 0xFF, signed_mode=1)
        assert await read_accumulator(dut) == before
        assert await read(dut, SELECT_PAIR_COUNT) == before_count
        assert await read(dut, SELECT_STATUS) == 0x10

    await clear_config(dut, 0b11, signed_mode=0)
    await issue(dut, COMMAND_MAC_LAST, pack_operands(3, 5))
    assert await read_accumulator(dut) == 15
    await issue(dut, COMMAND_MAC, pack_operands(15, 15))
    await issue(dut, COMMAND_FINISH)
    assert await read_accumulator(dut) == 15
    assert await read(dut, SELECT_PAIR_COUNT) == 1
    assert await read(dut, SELECT_STATUS) == 0x11


@cocotb.test()
async def test_core_overflow_status_in_every_architecture_mode(dut):
    """Selected conventional/dynamic sticky overflow reaches status bit 2."""
    await start(dut)

    for mode in range(4):
        await clear_config(dut, mode, signed_mode=0)
        dut.ui_in.value = pack_operands(15, 15)
        dut.uio_in.value = control_value(COMMAND_MAC, valid=1)
        for _ in range(4661):
            await RisingEdge(dut.clk)
        dut.uio_in.value = 0
        await Timer(1, unit="ns")
        assert await read_accumulator(dut) == (4661 * 225) & MASK
        status = await read(dut, SELECT_STATUS)
        assert status & 0x04  # selected accumulator overflow
        assert status & 0x08  # pair-count saturation/overflow

        await clear_config(dut, mode, signed_mode=1)
        dut.ui_in.value = pack_operands(7, 7)
        dut.uio_in.value = control_value(COMMAND_MAC, valid=1)
        for _ in range(10_700):
            await RisingEdge(dut.clk)
        dut.uio_in.value = 0
        await Timer(1, unit="ns")
        assert await read_accumulator(dut) == (10_700 * 49) & MASK
        status = await read(dut, SELECT_STATUS)
        assert status & 0x02  # latched signed mode
        assert status & 0x04  # signed positive overflow
        assert status & 0x08


def model_response(model, selector):
    state = model["conventional"] if model["mode"] == 0 else model["dynamic"]
    responses = {
        SELECT_ACC_LOW: state & 0xFF,
        SELECT_ACC_MIDDLE: (state >> 8) & 0xFF,
        SELECT_ACC_HIGH: (state >> 16) & 0xF,
        SELECT_PAIR_COUNT: model["count"],
        SELECT_STATUS: (
            model["done"]
            | (model["signed"] << 1)
            | (model["acc_overflow"] << 2)
            | (model["count_overflow"] << 3)
            | (model["protocol_error"] << 4)
        ),
        SELECT_LAST_PRODUCT: model["last_product"],
        SELECT_CONFIGURATION: (
            (model["zero_skip"] << 3)
            | (model["mode"] << 1)
            | model["signed"]
        ),
        SELECT_DESIGN_ID: 0x42,
    }
    return responses[selector]


@cocotb.test()
async def test_core_constrained_random_command_stream(dut):
    """Check 25,000 mixed commands/resets against an independent model."""
    await start(dut)
    rng = random.Random(0x5EEDC0DE)

    def reset_model():
        return {
            "conventional": 0,
            "dynamic": 0,
            "mode": 0,
            "zero_skip": 0,
            "signed": 0,
            "count": 0,
            "last_product": 0,
            "done": 0,
            "acc_overflow": 0,
            "count_overflow": 0,
            "protocol_error": 0,
        }

    model = reset_model()

    for cycle in range(25_000):
        if rng.randrange(500) == 0:
            await reset(dut)
            model = reset_model()
            continue

        command = rng.choices(
            range(8), weights=(2, 4, 16, 4, 10, 1, 1, 1), k=1
        )[0]
        live_signed = rng.randrange(2)
        data = rng.randrange(256)
        expected_read = None

        if command == COMMAND_CLEAR:
            model = reset_model()
            model["mode"] = data & 0x3
            model["zero_skip"] = (data >> 2) & 1
            model["signed"] = live_signed
        elif command in (COMMAND_MAC, COMMAND_MAC_LAST):
            if model["done"]:
                model["protocol_error"] = 1
            else:
                a = (data >> 4) & 0xF
                b = data & 0xF
                mathematical_product = product(a, b, model["signed"])
                raw_product = mathematical_product & 0xFF
                addend = mathematical_product & MASK
                model["last_product"] = raw_product
                if model["count"] == 0xFF:
                    model["count_overflow"] = 1
                else:
                    model["count"] += 1

                if not (model["zero_skip"] and raw_product == 0):
                    key = "conventional" if model["mode"] == 0 else "dynamic"
                    old_state = model[key]
                    new_state = (old_state + addend) & MASK
                    if model["signed"]:
                        overflow = (
                            ((old_state >> 19) & 1) == ((addend >> 19) & 1)
                            and ((new_state >> 19) & 1)
                            != ((old_state >> 19) & 1)
                        )
                    else:
                        overflow = old_state + addend > MASK
                    model[key] = new_state
                    model["acc_overflow"] |= int(overflow)

                if command == COMMAND_MAC_LAST:
                    model["done"] = 1
        elif command == COMMAND_FINISH:
            if model["done"]:
                model["protocol_error"] = 1
            else:
                model["done"] = 1
        elif command == COMMAND_READ:
            expected_read = model_response(model, data & 0x7)
        else:
            model["protocol_error"] = 1

        await issue(dut, command, data, live_signed)

        actual_state = int(dut.integrated_accumulator_value.value)
        expected_state = (
            model["conventional"]
            if model["mode"] == 0
            else model["dynamic"]
        )
        assert actual_state == expected_state, f"state mismatch at cycle {cycle}"
        assert int(dut.integrated_pair_count.value) == model["count"]
        assert int(dut.integrated_done.value) == model["done"]
        assert int(dut.integrated_count_overflow.value) == model["count_overflow"]
        assert int(dut.integrated_protocol_error.value) == model["protocol_error"]
        assert ((int(dut.uio_out.value) >> 6) & 1) == (command == COMMAND_READ)
        if expected_read is not None:
            assert int(dut.uo_out.value) == expected_read, (
                f"read mismatch selector={data & 7} cycle={cycle}"
            )
