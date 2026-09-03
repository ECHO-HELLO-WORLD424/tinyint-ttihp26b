# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


ACCUMULATOR_MASK = (1 << 20) - 1

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


def control_value(*, command=0, signed_mode=0, valid=0):
    return (signed_mode << 4) | (command << 1) | valid


def pack_operands(activation, weight):
    return ((activation & 0xF) << 4) | (weight & 0xF)


def response_valid(dut):
    return (int(dut.uio_out.value) >> 6) & 1


def ready(dut):
    return (int(dut.uio_out.value) >> 5) & 1


async def reset_dut(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    assert ready(dut) == 0
    assert response_valid(dut) == 0
    assert int(dut.uo_out.value) == 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert ready(dut) == 1
    assert response_valid(dut) == 0
    assert (int(dut.uio_out.value) >> 7) == 0
    assert int(dut.uio_oe.value) == 0xE0
    assert (int(dut.uio_out.value) & 0x1F) == 0


async def start_test(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)


async def issue_command(dut, command, *, data=0, signed_mode=0):
    assert ready(dut) == 1
    dut.ui_in.value = data
    dut.uio_in.value = control_value(
        command=command, signed_mode=signed_mode, valid=1
    )
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.uio_in.value = control_value(signed_mode=signed_mode)


async def read_selector(dut, selector, *, signed_mode=0):
    # P3 protocol: the response byte is emitted two cycles after acceptance.
    await issue_command(
        dut, COMMAND_READ, data=selector, signed_mode=signed_mode
    )
    for _ in range(6):
        if response_valid(dut) == 1:
            break
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
    else:
        raise AssertionError("READ response_valid did not assert within 6 cycles")
    value = int(dut.uo_out.value)

    # The registered byte is retained, but valid is exactly one cycle for an
    # isolated read.
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert response_valid(dut) == 0
    assert int(dut.uo_out.value) == value
    return value


async def read_accumulator(dut, *, signed_mode=0):
    low = await read_selector(dut, SELECT_ACC_LOW, signed_mode=signed_mode)
    middle = await read_selector(
        dut, SELECT_ACC_MIDDLE, signed_mode=signed_mode
    )
    high = await read_selector(dut, SELECT_ACC_HIGH, signed_mode=signed_mode)
    assert high & 0xF0 == 0
    return low | (middle << 8) | ((high & 0xF) << 16)


@cocotb.test()
async def test_empty_vector_finish_and_transaction_restart(dut):
    """FINISH supports empty vectors and CLEAR starts a clean transaction."""
    await start_test(dut)

    await issue_command(dut, COMMAND_CLEAR, signed_mode=1)
    await issue_command(dut, COMMAND_FINISH, signed_mode=0)

    assert await read_accumulator(dut) == 0
    assert await read_selector(dut, SELECT_PAIR_COUNT) == 0
    status = await read_selector(dut, SELECT_STATUS)
    assert status == 0b00000011  # done and latched signed mode

    # A repeated completion is rejected without changing data/count/done.
    await issue_command(dut, COMMAND_FINISH)
    assert await read_accumulator(dut) == 0
    assert await read_selector(dut, SELECT_PAIR_COUNT) == 0
    status = await read_selector(dut, SELECT_STATUS)
    assert status == 0b00010011  # protocol error is sticky

    await issue_command(dut, COMMAND_CLEAR, signed_mode=0)
    assert await read_selector(dut, SELECT_STATUS) == 0


@cocotb.test()
async def test_signed_streaming_dot_product_and_both_completion_styles(dut):
    """Mixed-sign vectors accumulate one pair per consecutive clock."""
    await start_test(dut)

    vectors = [(-8, -8), (7, -8), (-3, 5), (-1, -1)]
    expected = sum(a * w for a, w in vectors) & ACCUMULATOR_MASK

    await issue_command(dut, COMMAND_CLEAR, signed_mode=1)

    # Hold valid high and change only the operands between edges to prove the
    # advertised one-pair-per-cycle throughput.
    dut.uio_in.value = control_value(
        command=COMMAND_MAC, signed_mode=0, valid=1
    )
    for activation, weight in vectors:
        dut.ui_in.value = pack_operands(activation, weight)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
    dut.uio_in.value = 0

    await issue_command(dut, COMMAND_FINISH)
    assert await read_accumulator(dut) == expected
    assert await read_selector(dut, SELECT_PAIR_COUNT) == len(vectors)
    assert await read_selector(dut, SELECT_LAST_PRODUCT) == 1
    assert await read_selector(dut, SELECT_STATUS) == 0b00000011

    # MAC_LAST performs the final accumulation and completion on one edge.
    await issue_command(dut, COMMAND_CLEAR, signed_mode=1)
    await issue_command(
        dut,
        COMMAND_MAC_LAST,
        data=pack_operands(-8, -8),
        signed_mode=0,
    )
    assert await read_accumulator(dut) == 64
    assert await read_selector(dut, SELECT_PAIR_COUNT) == 1
    assert await read_selector(dut, SELECT_STATUS) == 0b00000011


@cocotb.test()
async def test_unsigned_dot_product_and_mac_after_done_is_rejected(dut):
    """Unsigned products use zero extension and done protects final state."""
    await start_test(dut)

    await issue_command(dut, COMMAND_CLEAR, signed_mode=0)
    await issue_command(dut, COMMAND_MAC, data=pack_operands(15, 15))
    await issue_command(dut, COMMAND_MAC, data=pack_operands(8, 7))
    await issue_command(dut, COMMAND_MAC_LAST, data=pack_operands(3, 5))
    expected = 225 + 56 + 15
    assert await read_accumulator(dut) == expected
    assert await read_selector(dut, SELECT_PAIR_COUNT) == 3

    await issue_command(dut, COMMAND_MAC, data=pack_operands(15, 15))
    await issue_command(dut, COMMAND_MAC_LAST, data=pack_operands(15, 15))
    assert await read_accumulator(dut) == expected
    assert await read_selector(dut, SELECT_PAIR_COUNT) == 3
    assert await read_selector(dut, SELECT_LAST_PRODUCT) == 15
    assert await read_selector(dut, SELECT_STATUS) == 0b00010001


@cocotb.test()
async def test_registered_read_latency_and_back_to_back_reads(dut):
    """READ captures one byte per edge and supports consecutive responses."""
    await start_test(dut)

    await issue_command(dut, COMMAND_CLEAR, signed_mode=1)
    await issue_command(
        dut, COMMAND_MAC_LAST, data=pack_operands(-8, 7), signed_mode=0
    )
    expected = (-56) & ACCUMULATOR_MASK
    expected_bytes = [
        expected & 0xFF,
        (expected >> 8) & 0xFF,
        (expected >> 16) & 0xF,
    ]

    # Back-to-back READs pipeline: with the P3 two-cycle latency the
    # response to each READ appears two cycles after its own acceptance, one
    # response per cycle, in order.
    assert response_valid(dut) == 0
    dut.uio_in.value = control_value(command=COMMAND_READ, valid=1)
    for selector, expected_byte in enumerate(expected_bytes):
        dut.ui_in.value = selector
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        if selector >= 1:
            assert response_valid(dut) == 1
            assert int(dut.uo_out.value) == expected_bytes[selector - 1]
        if selector == len(expected_bytes) - 1:
            # Exactly one valid cycle per READ.
            dut.uio_in.value = control_value(signed_mode=0)

    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert response_valid(dut) == 1
    assert int(dut.uo_out.value) == expected_bytes[-1]

    dut.uio_in.value = 0
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert response_valid(dut) == 0
    assert int(dut.uo_out.value) == expected_bytes[-1]


@cocotb.test()
async def test_pair_counter_saturates_and_flags_overflow(dut):
    """The 256th accepted pair sets overflow without wrapping the count."""
    await start_test(dut)

    await issue_command(dut, COMMAND_CLEAR, signed_mode=0)
    dut.ui_in.value = pack_operands(0, 15)
    dut.uio_in.value = control_value(command=COMMAND_MAC, valid=1)
    for _ in range(256):
        await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.uio_in.value = 0
    await issue_command(dut, COMMAND_FINISH)

    assert await read_selector(dut, SELECT_PAIR_COUNT) == 255
    assert await read_accumulator(dut) == 0
    assert await read_selector(dut, SELECT_STATUS) == 0b00001001


@cocotb.test()
async def test_reset_cancels_pending_response_and_transaction(dut):
    """Asynchronous reset clears command state and the response pipeline."""
    await start_test(dut)

    await issue_command(dut, COMMAND_CLEAR, signed_mode=1)
    await issue_command(dut, COMMAND_MAC, data=pack_operands(-8, -8))
    await issue_command(dut, COMMAND_READ, data=SELECT_ACC_LOW)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert response_valid(dut) == 1

    # Assert reset between rising edges to exercise the asynchronous path.
    await Timer(2, unit="ns")
    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    assert ready(dut) == 0
    assert response_valid(dut) == 0
    assert int(dut.uo_out.value) == 0

    dut.uio_in.value = 0
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert ready(dut) == 1
    assert await read_accumulator(dut) == 0
    assert await read_selector(dut, SELECT_PAIR_COUNT) == 0
    assert await read_selector(dut, SELECT_STATUS) == 0


@cocotb.test()
async def test_random_signed_variable_length_dot_products(dut):
    """Directed-random signed vectors match a modulo-20-bit Python model."""
    await start_test(dut)
    rng = random.Random(0xD07C0DE)

    for transaction in range(128):
        length = rng.randrange(65)
        vectors = [
            (rng.randrange(-8, 8), rng.randrange(-8, 8))
            for _ in range(length)
        ]
        expected = sum(a * w for a, w in vectors) & ACCUMULATOR_MASK

        await issue_command(dut, COMMAND_CLEAR, signed_mode=1)
        if not vectors:
            await issue_command(dut, COMMAND_FINISH, signed_mode=rng.randrange(2))
        else:
            for activation, weight in vectors[:-1]:
                await issue_command(
                    dut,
                    COMMAND_MAC,
                    data=pack_operands(activation, weight),
                    signed_mode=rng.randrange(2),
                )
            activation, weight = vectors[-1]
            await issue_command(
                dut,
                COMMAND_MAC_LAST,
                data=pack_operands(activation, weight),
                signed_mode=rng.randrange(2),
            )

        actual = await read_accumulator(dut, signed_mode=rng.randrange(2))
        assert actual == expected, (
            f"transaction {transaction}, length {length}: "
            f"expected 0x{expected:05x}, got 0x{actual:05x}"
        )
        assert await read_selector(dut, SELECT_PAIR_COUNT) == length
        status = await read_selector(dut, SELECT_STATUS)
        assert status == 0x03  # done and signed, with no sticky errors
