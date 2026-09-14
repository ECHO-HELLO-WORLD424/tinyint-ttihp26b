#!/usr/bin/env python3
"""Host-side driver for the pico2-ice TT protocol verification.

Uploads fpga/build/tt_um_echoworld424_tpv.bin and fpga/board_test.py to the
board, runs the board-side test over the MicroPython REPL with mpremote, and
checks the returned status bytes against the protocol documented in
docs/info.md.

Usage:
    PICO_PORT=/dev/cu.usbmodem1101 MPREMOTE=mpremote python3 fpga/verify.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BITSTREAM = os.path.join(HERE, "build", "tt_um_echoworld424_tpv.bin")
BOARD_TEST = os.path.join(HERE, "board_test.py")
REMOTE_BITSTREAM = ":" + os.path.basename(BITSTREAM)
PORT = os.environ.get("PICO_PORT", "/dev/cu.usbmodem1101")
MPREMOTE = os.environ.get("MPREMOTE", "mpremote")

FAILURES = []


def check(cond, msg):
    tag = "PASS" if cond else "FAIL"
    print("  [%s] %s" % (tag, msg))
    if not cond:
        FAILURES.append(msg)


def mpremote(*args, timeout=300):
    cmd = [MPREMOTE, "connect", PORT] + list(args)
    print("+ " + " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        sys.stderr.write(p.stdout)
        sys.stderr.write(p.stderr)
        raise SystemExit("mpremote failed: %s" % (args,))
    return p.stdout + p.stderr


def decode(line):
    marker = "@@JSON@@ "
    i = line.find(marker)
    return json.loads(line[i + len(marker):]) if i >= 0 else None


def main():
    if not os.path.exists(BITSTREAM):
        raise SystemExit("missing %s; run fpga/build_bitstream.sh first" % BITSTREAM)

    mpremote("fs", "cp", BITSTREAM, REMOTE_BITSTREAM)
    mpremote("fs", "cp", BOARD_TEST, ":board_test.py")
    out = mpremote("exec", "import board_test; board_test.main()", timeout=600)

    cases = {}
    order = []
    for line in out.splitlines():
        rec = decode(line)
        if rec is not None:
            cases[rec["case"]] = rec
            order.append(rec["case"])
    if not cases:
        sys.stderr.write(out)
        raise SystemExit("no JSON records returned by the board")

    print("\n=== board-side protocol verification ===")

    prog = cases.get("program", {})
    print("program:")
    check(prog.get("cdone") == 1, "FPGA CDONE high after CRAM load")

    def case(name):
        rec = cases.get(name)
        if rec is None:
            check(False, "case %s missing" % name)
            return None
        return rec

    c = case("masked_canary")
    if c:
        print("masked_canary (FORCE_CAN, WORST pattern):")
        check(c["missing"] == 0, "all 16 status bytes read (missing=%d)" % c["missing"])
        check(c["echo"] == 0x00, "cfg echo byte 8 == 0x00 (got 0x%02X)" % c["echo"])
        check(c["err_cnt"] == 0, "err_cnt == 0 (got %d)" % c["err_cnt"])
        check(c["gen_cnt"] == 0 and c["mat_cnt"] == 0,
              "masked RO counters stay at 0 (gen=%d mat=%d)" % (c["gen_cnt"], c["mat_cnt"]))
        check(c["stat"] == 0xE4, "stat == 0xE4 deadflags+canary1+win0 (got 0x%02X)" % c["stat"])
        check(c["ops"] >= c["frames"] - 3,
              "ops advanced: %d for %d frames" % (c["ops"], c["frames"]))

    c = case("canary_running")
    if c:
        print("canary_running (unmasked canaries):")
        check(c["err_cnt"] == 0, "err_cnt == 0 (got %d)" % c["err_cnt"])
        check(c["gen_cnt"] > 0, "generic RO counting (got %d)" % c["gen_cnt"])
        check(c["mat_cnt"] > 0, "matched RO counting (got %d)" % c["mat_cnt"])
        check(c["stat"] == 0x84, "stat == 0x84 canary1+win0 (got 0x%02X)" % c["stat"])

    c = case("force_error_worst")
    if c:
        print("force_error_worst (FORCE_ERR, seg taps 1/1/1/1):")
        check(c["echo"] == 0x55, "cfg echo byte 8 == 0x55 (got 0x%02X)" % c["echo"])
        check(c["err_cnt"] == c["ops"] - 1,
              "one error per checked frame: err=%d ops=%d" % (c["err_cnt"], c["ops"]))
        check(c["err_dut"] == 0x00,
              "first failed DUT byte inverts 0x1FFFF -> 0x00 (got 0x%02X)" % c["err_dut"])
        check((c["stat"] >> 4) & 1 == 1, "err_seen flag set")
        check(c["stat"] == 0xF4, "stat == 0xF4 (got 0x%02X)" % c["stat"])

    c = case("freeze_hold")
    if c:
        print("freeze_hold (FREEZE must stop measurement state):")
        check(c["gen_cnt"] > 0, "canaries running before freeze (got %d)" % c["gen_cnt"])
        check(c["ops"] == c["frozen_ops"],
              "ops held while frozen (%d vs %d)" % (c["ops"], c["frozen_ops"]))
        check(c["err_cnt"] == c["frozen_err"],
              "err_cnt held while frozen (%d vs %d)" % (c["err_cnt"], c["frozen_err"]))
        check(c["gen_cnt"] == c["frozen_gen"],
              "gen_cnt held while frozen (%d vs %d)" % (c["gen_cnt"], c["frozen_gen"]))

    c = case("reconfigure")
    if c:
        print("reconfigure (rst pulse + new config):")
        check(c["missing"] == 0, "all 16 status bytes read")
        check(c["err_cnt"] == 0, "counters cleared (err_cnt=%d)" % c["err_cnt"])
        check(c["stat"] == 0x89, "stat == 0x89 canary2+win1 (got 0x%02X)" % c["stat"])
        check(c["gen_cnt"] > 0 and c["mat_cnt"] > 0, "canaries restarted")
        check(c["ops"] >= c["frames"] - 3, "ops restarted (%d)" % c["ops"])

    c = case("taps_echo")
    if c:
        print("taps_echo (serial ui[7:0] config path):")
        check(c["echo"] == 0x1B,
              "cfg echo byte 8 == taps {3,2,1,0} = 0x1B (got 0x%02X)" % c["echo"])
        check(c["err_cnt"] == 0, "err_cnt == 0 (got %d)" % c["err_cnt"])
        check(c["stat"] == 0xE4, "stat == 0xE4 (got 0x%02X)" % c["stat"])

    print("\n%d checks failed" % len(FAILURES))
    for f in FAILURES:
        print("  FAIL: " + f)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
