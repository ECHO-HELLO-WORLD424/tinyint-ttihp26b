# SPDX-FileCopyrightText: © 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
#
# Rigorous test suite for the timing-prediction test vehicle.
#
# Coverage:
#   - reset/config latch, uio direction switching, config echo
#   - functional correctness of DUT + bit-serial oracle across all pattern
#     classes and several delay-bank configurations (zero errors required)
#   - exact error accounting via FORCE_ERR (counter values, first-error
#     capture, op counter) including known expected operands (PRBS + WORST)
#   - canary counters: FORCE_CAN dead flags, quantitative window counts
#   - freeze semantics, mid-run reconfiguration, frame pacing

import os

import cocotb
from cocotb.triggers import Timer

FRAME = 19  # cycles per measured operation

# Gate-level simulation: the PDK cell models are zero-delay functional, so
# the ring-oscillator loops would spin forever. GL runs therefore force
# FORCE_CAN on every configuration (stalling the loops) and assert counters
# stay at zero. The exact RO-count test is RTL-only.
GL = os.environ.get("GL_TEST") == "yes"
CLK_HALF = 50 if GL else 5  # GL runs at 10 MHz, RTL at 100 MHz


# ---------------------------------------------------------------- helpers --


async def cyc(dut, n=1):
    """Manually toggle the clock n times (exact cycle control)."""
    for _ in range(n):
        dut.clk.value = 1
        await Timer(CLK_HALF, "ns")
        dut.clk.value = 0
        await Timer(CLK_HALF, "ns")


def cfg_word(seg=(0, 0, 0, 0), pat=0, cansel=0, winsel=0, force_can=None, force_err=0):
    if force_can is None:
        force_can = 1 if GL else 0
    return (
        (seg[0] & 3)
        | ((seg[1] & 3) << 2)
        | ((seg[2] & 3) << 4)
        | ((seg[3] & 3) << 6)
        | ((pat & 3) << 8)
        | ((cansel & 3) << 10)
        | ((winsel & 3) << 12)
        | (force_can << 14)
        | (force_err << 15)
    )


async def configure(dut, word, settle=8):
    """Reset the design and latch the 16-bit config word (ui = LSB, uio = MSB).

    The config word must be held until three clock cycles after rst_n
    release (the on-chip boot counter commits it at the boot==2 edge).
    """
    dut.clk.value = 0
    dut.rst_n.value = 0
    dut.ui_in.value = word & 0xFF
    dut.uio_in.value = (word >> 8) & 0xFF
    await cyc(dut, 4)
    dut.rst_n.value = 1
    await cyc(dut, 3)  # boot window: cfg commits at the boot==2 edge
    dut.ui_in.value = 0  # release config pins (ui[7] = freeze must be low)
    dut.uio_in.value = 0  # board model: host switches uio to inputs
    await cyc(dut, settle)


async def freeze(dut, on):
    dut.ui_in.value = 0x80 if on else 0x00
    await cyc(dut, 2)


async def read_status(dut):
    """Sample all 16 readout bytes (pointer auto-increments on uo[3:0])."""
    vals = {}
    for _ in range(48):
        dut.clk.value = 1
        await Timer(CLK_HALF, "ns")
        ptr = int(dut.uo_out.value) & 0xF
        vals[ptr] = int(dut.uio_out.value)
        dut.clk.value = 0
        await Timer(CLK_HALF, "ns")
        if len(vals) == 16:
            break
    assert len(vals) == 16, f"incomplete readout: got pointers {sorted(vals)}"
    return {
        "err_cnt": vals[0] | (vals[1] << 8),
        "gen_cnt": vals[2] | (vals[3] << 8),
        "mat_cnt": vals[4] | (vals[5] << 8),
        "ops": vals[6] | (vals[7] << 8),
        "cfg_echo": vals[8],
        "stat": vals[9],
        "err_dut": vals[10],
        "err_chk": vals[11],
    }


def lfsr_step(s):
    fb = ((s >> 15) ^ (s >> 13) ^ (s >> 12) ^ (s >> 10)) & 1
    return ((s << 1) | fb) & 0xFFFF


def prbs_op0():
    """First compared PRBS operand pair. The comb decode reflects the state
    after the first load, so the LFSR has advanced twice from the seed."""
    n = lfsr_step(lfsr_step(0xACE1))
    a = n
    b = ((n & 0x7F) << 9) | (n >> 7)
    cin = ((n >> 15) ^ (n >> 7) ^ (n >> 3)) & 1
    return a, b, cin


# ------------------------------------------------------------------ tests --


@cocotb.test()
async def test_reset_and_config_echo(dut):
    """Reset behavior, uio direction switching, config echo, healthy flags."""
    word = cfg_word(seg=(1, 2, 3, 0), pat=1, cansel=2, winsel=0)
    dut.clk.value = 0
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await cyc(dut, 2)
    assert int(dut.uio_oe.value) == 0x00, "uio must be input during reset"

    await configure(dut, word)
    assert int(dut.uio_oe.value) == 0xFF, "uio must switch to output after reset"

    await cyc(dut, 300)  # let the 2^8 measurement window complete
    await freeze(dut, True)
    s = await read_status(dut)
    await freeze(dut, False)

    assert s["cfg_echo"] == (word & 0xFF), hex(s["cfg_echo"])
    # stat = {run, mat_dead, gen_dead, err_seen=0, cansel=2, winsel=0}
    # GL stalls the loops, so both dead flags are set there
    assert s["stat"] == (0b11101000 if GL else 0b10001000), hex(s["stat"])
    assert s["err_cnt"] == 0
    if GL:
        assert s["gen_cnt"] == 0 and s["mat_cnt"] == 0  # loops stalled in GL
    else:
        assert s["gen_cnt"] > 0 and s["mat_cnt"] > 0, "RO canaries must be counting"
    assert s["ops"] >= 15  # ~308 cycles / 18


@cocotb.test()
async def test_functional_no_errors(dut):
    """DUT + oracle must agree exactly: all patterns x several delay configs."""
    for pat in range(4):
        for segs in [(0, 0, 0, 0), (3, 3, 3, 3), (2, 1, 3, 0)]:
            word = cfg_word(seg=segs, pat=pat, cansel=1, winsel=0)
            await configure(dut, word)
            await cyc(dut, 150 * FRAME)
            await freeze(dut, True)
            s = await read_status(dut)
            await freeze(dut, False)
            tag = f"pat={pat} segs={segs}"
            assert s["ops"] == 150, f"{tag}: ops={s['ops']}"
            assert s["err_cnt"] == 0, f"{tag}: err_cnt={s['err_cnt']}"
            assert (s["stat"] >> 4) & 1 == 0, f"{tag}: err_seen set"
            if GL:
                assert s["gen_cnt"] == 0 and s["mat_cnt"] == 0
            else:
                assert s["gen_cnt"] > 0 and s["mat_cnt"] > 0, f"{tag}: RO dead"


@cocotb.test()
async def test_force_err_accounting(dut):
    """FORCE_ERR must produce exactly one error per checked frame, with the
    first captured pair equal to WORST op1 = 0xFFFF+0xFFFF+1 -> 0x1FFFF."""
    word = cfg_word(seg=(1, 1, 1, 1), pat=1, cansel=1, winsel=0, force_err=1)
    await configure(dut, word)
    await cyc(dut, 100 * FRAME)
    await freeze(dut, True)
    s = await read_status(dut)
    await freeze(dut, False)

    assert s["ops"] == 100, s["ops"]
    # op P_0 is the first compared (boundary 2); every frame errors under force
    assert s["err_cnt"] == 99, s["err_cnt"]
    assert (s["stat"] >> 4) & 1 == 1, "err_seen must be set"
    # first compared WORST op is idx=1: 0xFFFF+0xFFFF+1 -> 0x1FFFF (inverted)
    assert s["err_dut"] == 0x00, hex(s["err_dut"])
    assert s["err_chk"] == 0x00, hex(s["err_chk"])  # byte 11 reserved


@cocotb.test()
async def test_force_can_flags(dut):
    """FORCE_CAN must freeze both RO counters at zero and flag them dead."""
    word = cfg_word(seg=(0, 0, 0, 0), pat=0, cansel=1, winsel=0, force_can=1)
    await configure(dut, word)
    await cyc(dut, 300)
    await freeze(dut, True)
    s = await read_status(dut)
    await freeze(dut, False)

    assert s["gen_cnt"] == 0 and s["mat_cnt"] == 0
    assert s["err_cnt"] == 0
    assert (s["stat"] >> 6) & 1 == 1, "mat_ro_dead must be set"
    assert (s["stat"] >> 5) & 1 == 1, "gen_ro_dead must be set"


@cocotb.test(skip=GL)
async def test_canary_window_counts(dut):
    """RO edge counters must reflect the known simulated loop frequencies.

    With TPV_GDELAY=1: generic RO (sel=3) loop = 42 line + 8 tail + close +
    nand = 52 gate delays -> 104 ns period. Matched RO (sel=3) loop = 2*66 +
    8 + close + nand = 144 -> 288 ns period. Window = 2^8 cycles @ 10 ns =
    2560 ns. Counts are sampled right after the window freezes.
    """
    word = cfg_word(seg=(0, 0, 0, 0), pat=3, cansel=3, winsel=0)
    await configure(dut, word)
    await cyc(dut, 300)
    await freeze(dut, True)
    s = await read_status(dut)
    await freeze(dut, False)

    assert 20 <= s["gen_cnt"] <= 27, s["gen_cnt"]  # ~2560/104 = 24
    assert 6 <= s["mat_cnt"] <= 11, s["mat_cnt"]  # ~2560/288 = 9


@cocotb.test()
async def test_prbs_first_error_capture(dut):
    """PRBS op0 (computed independently here) must be the first captured
    error pair under FORCE_ERR, and the run must be deterministic."""
    word = cfg_word(seg=(2, 2, 2, 2), pat=0, cansel=0, winsel=0, force_err=1)
    await configure(dut, word)
    await cyc(dut, 10 * FRAME)
    await freeze(dut, True)
    s = await read_status(dut)
    await freeze(dut, False)

    a, b, cin = prbs_op0()
    total = a + b + cin  # 17-bit true result
    inv = (~total) & 0x1FFFF
    assert s["err_dut"] == inv & 0xFF, (hex(s["err_dut"]), hex(inv & 0xFF))
    assert s["err_cnt"] == 9, s["err_cnt"]  # every frame from boundary 2

    # determinism: identical rerun
    await configure(dut, word)
    await cyc(dut, 10 * FRAME)
    await freeze(dut, True)
    s2 = await read_status(dut)
    await freeze(dut, False)
    assert s2["err_dut"] == s["err_dut"]
    assert s2["err_cnt"] == s["err_cnt"]


@cocotb.test()
async def test_freeze_holds_counters(dut):
    """While frozen, all counters must hold even with the clock running."""
    word = cfg_word(seg=(1, 0, 1, 0), pat=1, cansel=0, winsel=0, force_err=1)
    await configure(dut, word)
    await cyc(dut, 50 * FRAME)
    await freeze(dut, True)
    s1 = await read_status(dut)
    await cyc(dut, 500)  # clock keeps running while frozen
    s2 = await read_status(dut)
    await freeze(dut, False)
    assert s1 == s2, (s1, s2)


@cocotb.test()
async def test_reconfigure_midrun(dut):
    """A reset pulse must clear counters and latch the new config."""
    w1 = cfg_word(seg=(0, 0, 0, 0), pat=1, cansel=0, winsel=0, force_err=1)
    await configure(dut, w1)
    await cyc(dut, 20 * FRAME)
    await freeze(dut, True)
    s_old = await read_status(dut)
    await freeze(dut, False)
    assert s_old["ops"] == 20 and s_old["err_cnt"] == 19

    w2 = cfg_word(seg=(3, 3, 3, 3), pat=3, cansel=3, winsel=1, force_err=0)
    await configure(dut, w2)
    await cyc(dut, 1100)  # window 2^10 = 1024 cycles completes
    await freeze(dut, True)
    s = await read_status(dut)
    await freeze(dut, False)

    assert s["cfg_echo"] == 0xFF, hex(s["cfg_echo"])
    assert s["ops"] == 58, s["ops"]  # (settle + 1100) // 19
    assert s["err_cnt"] == 0, "force_err must be off after reconfigure"
    assert (s["stat"] >> 4) & 1 == 0
    if GL:
        assert s["gen_cnt"] == 0 and s["mat_cnt"] == 0
    else:
        assert s["gen_cnt"] > 0 and s["mat_cnt"] > 0


@cocotb.test()
async def test_frame_strobe_pacing(dut):
    """uo[7] must pulse once per 18-cycle frame (36 strobes in 648 cycles)."""
    await configure(dut, cfg_word(seg=(0, 0, 0, 0), pat=3, cansel=0, winsel=0))
    strobes = 0
    for _ in range(36 * FRAME):
        dut.clk.value = 1
        await Timer(CLK_HALF, "ns")
        strobes += (int(dut.uo_out.value) >> 7) & 1
        dut.clk.value = 0
        await Timer(CLK_HALF, "ns")
    assert strobes == 36, strobes
