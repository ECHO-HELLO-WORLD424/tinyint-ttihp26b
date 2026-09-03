# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


MASK = (1 << 20) - 1
FINISH, CLEAR, MAC, MAC_LAST, READ = range(5)
ACC_LOW, ACC_MIDDLE, ACC_HIGH, PAIR_COUNT = range(4)
STATUS, LAST_PRODUCT, CONFIGURATION, DESIGN_ID = range(4, 8)


def control(command=0, signed=0, valid=0):
    return (signed << 4) | (command << 1) | valid


def pack(a, b):
    return ((a & 0xF) << 4) | (b & 0xF)


def int4(value):
    value &= 0xF
    return value - 16 if value & 8 else value


def multiply(a, b, signed):
    return int4(a) * int4(b) if signed else (a & 0xF) * (b & 0xF)


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


async def issue(dut, command, data=0, signed=0):
    dut.ui_in.value = data
    dut.uio_in.value = control(command, signed, 1)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.uio_in.value = control(signed=signed)


async def read(dut, selector):
    # P3 protocol: the response byte is emitted two cycles after acceptance.
    await issue(dut, READ, selector)
    for _ in range(6):
        if (int(dut.uio_out.value) >> 6) & 1:
            return int(dut.uo_out.value)
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
    raise AssertionError("READ response_valid did not assert within 6 cycles")


async def read_accumulator(dut):
    return (
        await read(dut, ACC_LOW)
        | ((await read(dut, ACC_MIDDLE)) << 8)
        | (((await read(dut, ACC_HIGH)) & 0xF) << 16)
    )


async def clear_config(dut, mode, signed, zero_skip=0):
    await issue(dut, CLEAR, mode | (zero_skip << 2), signed)


@cocotb.test()
async def test_gate_core_configuration_and_matched_modes(dut):
    """All modes/configuration selectors survive synthesis and remain exact."""
    await start(dut)
    assert await read(dut, CONFIGURATION) == 0
    assert await read(dut, DESIGN_ID) == 0x42

    rng = random.Random(0x6A7E)
    for signed in (0, 1):
        vectors = [
            (
                rng.randrange(-8, 8) if signed else rng.randrange(16),
                rng.randrange(-8, 8) if signed else rng.randrange(16),
            )
            for _ in range(2048)
        ]
        expected = sum(multiply(a, b, signed) for a, b in vectors) & MASK
        for zero_skip in (0, 1):
            for mode in range(4):
                await clear_config(dut, mode, signed, zero_skip)
                expected_config = (zero_skip << 3) | (mode << 1) | signed
                assert await read(dut, CONFIGURATION) == expected_config
                dut.uio_in.value = control(MAC, 1 - signed, 1)
                for a, b in vectors:
                    dut.ui_in.value = pack(a, b)
                    await RisingEdge(dut.clk)
                dut.uio_in.value = 0
                await Timer(1, unit="ns")
                assert await read_accumulator(dut) == expected
                assert await read(dut, PAIR_COUNT) == 0xFF


@cocotb.test()
async def test_gate_core_errors_completion_zero_skip_and_overflow(dut):
    """Gate state preserves protocol errors, completion, skip, and overflow."""
    await start(dut)

    for mode in range(4):
        await clear_config(dut, mode, signed=0, zero_skip=1)
        for _ in range(3):
            await issue(dut, MAC, pack(0, 15), signed=1)
        assert await read_accumulator(dut) == 0
        assert await read(dut, PAIR_COUNT) == 3
        assert await read(dut, LAST_PRODUCT) == 0

        await issue(dut, MAC_LAST, pack(3, 5))
        await issue(dut, MAC, pack(15, 15))
        assert await read_accumulator(dut) == 15
        assert await read(dut, PAIR_COUNT) == 4
        assert await read(dut, STATUS) == 0x11

        await clear_config(dut, mode, signed=0)
        dut.ui_in.value = pack(15, 15)
        dut.uio_in.value = control(MAC, valid=1)
        for _ in range(4661):
            await RisingEdge(dut.clk)
        dut.uio_in.value = 0
        await Timer(1, unit="ns")
        assert await read_accumulator(dut) == (4661 * 225) & MASK
        assert await read(dut, STATUS) & 0x0C == 0x0C

        await clear_config(dut, mode, signed=0)
        await issue(dut, 0b101, 0xAA)
        await issue(dut, 0b110, 0x55)
        await issue(dut, 0b111, 0xFF)
        assert await read(dut, STATUS) == 0x10


def new_model():
    return {
        "state": 0,
        "mode": 0,
        "skip": 0,
        "signed": 0,
        "count": 0,
        "last": 0,
        "done": 0,
        "acc_ov": 0,
        "count_ov": 0,
        "proto": 0,
    }


def expected_read(model, selector):
    return {
        ACC_LOW: model["state"] & 0xFF,
        ACC_MIDDLE: (model["state"] >> 8) & 0xFF,
        ACC_HIGH: (model["state"] >> 16) & 0xF,
        PAIR_COUNT: model["count"],
        STATUS: (
            model["done"]
            | (model["signed"] << 1)
            | (model["acc_ov"] << 2)
            | (model["count_ov"] << 3)
            | (model["proto"] << 4)
        ),
        LAST_PRODUCT: model["last"],
        CONFIGURATION: (
            (model["skip"] << 3)
            | (model["mode"] << 1)
            | model["signed"]
        ),
        DESIGN_ID: 0x42,
    }[selector]


@cocotb.test()
async def test_gate_core_random_architectural_model(dut):
    """Check 15,000 random commands using only physical architectural pins."""
    await start(dut)
    rng = random.Random(0x6A7EC0DE)
    model = new_model()
    pending_read = None

    for cycle in range(15_000):
        if rng.randrange(700) == 0:
            await reset(dut)
            model = new_model()
            # A reset discards any in-flight READ response on both sides.
            pending_read = None
            continue

        command = rng.choices(range(8), (2, 4, 16, 4, 8, 1, 1, 1), k=1)[0]
        data = rng.randrange(256)
        live_signed = rng.randrange(2)
        read_value = expected_read(model, data & 7) if command == READ else None

        if command == CLEAR:
            model = new_model()
            model["mode"] = data & 3
            model["skip"] = (data >> 2) & 1
            model["signed"] = live_signed
        elif command in (MAC, MAC_LAST):
            if model["done"]:
                model["proto"] = 1
            else:
                value = multiply(data >> 4, data, model["signed"])
                raw = value & 0xFF
                addend = value & MASK
                model["last"] = raw
                if model["count"] == 0xFF:
                    model["count_ov"] = 1
                else:
                    model["count"] += 1
                if not (model["skip"] and raw == 0):
                    old = model["state"]
                    new = (old + addend) & MASK
                    overflow = (
                        (((old >> 19) & 1) == ((addend >> 19) & 1))
                        and (((new >> 19) & 1) != ((old >> 19) & 1))
                        if model["signed"]
                        else old + addend > MASK
                    )
                    model["state"] = new
                    model["acc_ov"] |= int(overflow)
                if command == MAC_LAST:
                    model["done"] = 1
        elif command == FINISH:
            if model["done"]:
                model["proto"] = 1
            else:
                model["done"] = 1
        elif command >= 0b101:
            model["proto"] = 1

        await issue(dut, command, data, live_signed)

        # P3 protocol: the READ response becomes valid two cycles after
        # acceptance, so the byte checked here belongs to the READ issued
        # one iteration ago; it stays bit-identical to the model.
        assert ((int(dut.uio_out.value) >> 6) & 1) == (pending_read is not None)
        if pending_read is not None:
            assert int(dut.uo_out.value) == pending_read
            pending_read = None
        pending_read = read_value

        if cycle % 97 == 0 and command != READ:
            assert await read_accumulator(dut) == model["state"]
            for selector in (
                PAIR_COUNT,
                STATUS,
                LAST_PRODUCT,
                CONFIGURATION,
                DESIGN_ID,
            ):
                assert await read(dut, selector) == expected_read(model, selector)
