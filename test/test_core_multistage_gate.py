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
    await issue(dut, READ, selector)
    assert (int(dut.uio_out.value) >> 6) & 1
    return int(dut.uo_out.value)


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
                # P4: the monitor starts at the latched mode, so the former
                # constant-zero upper nibble reports it until MACs retune.
                expected_config = (
                    (mode << 4) | (zero_skip << 3) | (mode << 1) | signed
                )
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
    result = {
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
    result["monitor"] = BoundaryMonitor(result["mode"])
    return result


class BoundaryMonitor:
    """Python mirror of the RTL adaptive-boundary monitor.

    Every accepted MAC advances a 64-MAC window; written MACs whose extended
    product flips its top bit (the sign-extension region changed) count as
    extension events. A window decision (boundary 8 when the window saw at
    least 16 extension events, boundary 20 otherwise) applies after it
    repeats in two consecutive windows. CLEAR restarts at the latched mode.
    """

    WINDOW = 64
    EXTENSION_THRESHOLD = 16

    def __init__(self, initial_mode):
        self.effective = initial_mode & 0x3
        self.window_count = 0
        self.extension_events = 0
        self.previous_extension_bit = 0
        self.previous_decision = initial_mode & 0x3

    def on_mac(self, written, addend):
        # The RTL samples the window decision from the event count as it
        # stands before the acceptance edge, so a flip on the 64th MAC of a
        # window belongs to the decision of the next window, not this one.
        decision_events = self.extension_events
        if written:
            extension_bit = (addend >> 19) & 1
            if extension_bit != self.previous_extension_bit:
                self.extension_events += 1
            self.previous_extension_bit = extension_bit
        self.window_count += 1
        if self.window_count == self.WINDOW:
            self.window_count = 0
            decision = (
                0b01 if decision_events >= self.EXTENSION_THRESHOLD else 0b00
            )
            apply_decision = decision == self.previous_decision
            self.previous_decision = decision
            if apply_decision:
                self.effective = decision
            self.extension_events = 0


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
            (model["monitor"].effective << 4)
            | (model["skip"] << 3)
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

    for cycle in range(15_000):
        if rng.randrange(700) == 0:
            await reset(dut)
            model = new_model()
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
            model["monitor"] = BoundaryMonitor(model["mode"])
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
                written = not (model["skip"] and raw == 0)
                model["monitor"].on_mac(written, addend)
        elif command == FINISH:
            if model["done"]:
                model["proto"] = 1
            else:
                model["done"] = 1
        elif command >= 0b101:
            model["proto"] = 1

        await issue(dut, command, data, live_signed)
        if read_value is not None:
            assert int(dut.uo_out.value) == read_value

        if cycle % 97 == 0:
            assert await read_accumulator(dut) == model["state"]
            for selector in (
                PAIR_COUNT,
                STATUS,
                LAST_PRODUCT,
                CONFIGURATION,
                DESIGN_ID,
            ):
                assert await read(dut, selector) == expected_read(model, selector)
