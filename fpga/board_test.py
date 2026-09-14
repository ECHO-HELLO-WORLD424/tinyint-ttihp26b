# pico2-ice board-side verification for tt_um_echoworld424_tpv.
#
# Runs on the RP2350 under the tinyvision MicroPython firmware. Programs the
# bitstream from fpga/build/ into the iCE40UP5K with the `ice` module, drives
# the TT protocol over the pico2-ice harness pins (see tt_fpga_pico2ice.v and
# pico2ice.pcf) and prints one JSON record per test case.
#
# Host side: fpga/verify.py (uploads this file and the bitstream, runs main()).

from machine import Pin, mem32
import ice
import json
import time

BITSTREAM = "/tt_um_echoworld424_tpv.bin"
CLK_HZ = 5000            # 200 us period; readable with one SIO load per sample
FRAME_US = int(19 * 1e6 / CLK_HZ)

SIO_GPIO_IN = 0xD0000004
# uo[0..3] = RP2350 GPIO7, GPIO6, GPIO5, GPIO4
UO_GPIO = (7, 6, 5, 4)
# uio[0..7] = RP2350 GPIO23, 27, 26, 25, 30, 24, 28, 29
UIO_GPIO = (23, 27, 26, 25, 30, 24, 28, 29)

P_CDONE = 40
P_CLK = 21
P_RST = 22
P_UICFG = 20
P_CRESET = 31
P_CRAM_CS = 5
P_CRAM_MOSI = 4
P_CRAM_SCK = 6

UIO_PINS = (23, 27, 26, 25, 30, 24, 28, 29)   # uio[0..7]
UO_PINS = (7, 6, 5, 4)                        # uo[0..3]


def emit(obj):
    print("@@JSON@@ " + json.dumps(obj))


def cfg_word(seg=(0, 0, 0, 0), pat=0, can=0, win=0, force_can=0, force_err=0):
    return (
        (seg[0] & 3)
        | ((seg[1] & 3) << 2)
        | ((seg[2] & 3) << 4)
        | ((seg[3] & 3) << 6)
        | ((pat & 3) << 8)
        | ((can & 3) << 10)
        | ((win & 3) << 12)
        | ((force_can & 1) << 14)
        | ((force_err & 1) << 15)
    )


def program():
    fpga = ice.fpga(
        cdone=Pin(P_CDONE),
        clock=Pin(P_CLK),
        creset=Pin(P_CRESET),
        cram_cs=Pin(P_CRAM_CS),
        cram_mosi=Pin(P_CRAM_MOSI),
        cram_sck=Pin(P_CRAM_SCK),
        frequency=CLK_HZ / 1e6,
    )
    fpga.start()
    with open(BITSTREAM, "rb") as f:
        fpga.cram(f)
    time.sleep_ms(50)
    return fpga


class Harness:
    def __init__(self):
        self.rst = Pin(P_RST, Pin.OUT, value=0)
        self.ui = Pin(P_UICFG, Pin.OUT, value=0)
        self.uio = [Pin(p, Pin.OUT, value=0) for p in UIO_PINS]
        self.uo = [Pin(p, Pin.IN) for p in UO_PINS]

    def _rising(self, timeout_ms=100):
        # uo[0] is RP2350 GPIO7 and mirrors clk while the harness is in reset.
        mask = 1 << UO_GPIO[0]
        t0 = time.ticks_ms()
        while mem32[SIO_GPIO_IN] & mask:
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
                raise OSError("clock sync timeout (waiting low)")
        while not (mem32[SIO_GPIO_IN] & mask):
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
                raise OSError("clock sync timeout (waiting high)")

    def configure(self, word):
        """Hold reset, drive uio config, shift ui[7:0] in MSB first, release."""
        self.rst.value(0)
        self.ui.value(0)
        time.sleep_ms(2)                 # >= 8 clocks of shadow zeros
        self._rising()                   # align to a rising clk edge
        for i, p in enumerate(self.uio):  # uio = config bits [15:8]
            p.init(Pin.OUT)
            p.value((word >> (8 + i)) & 1)
        b = word & 0xFF                  # ui = config bits [7:0]
        for i in range(7, -1, -1):
            self.ui.value((b >> i) & 1)
            self._rising()
        self.rst.value(1)                # release right after the last shift
        for p in self.uio:
            p.init(Pin.IN)               # design now drives the status byte
        time.sleep_ms(1)                 # >= 3 clocks for the boot counter
        self.ui.value(0)                 # ui[7] = FREEZE; deassert after boot

    def freeze(self, on):
        self.ui.value(1 if on else 0)
        time.sleep_ms(2)

    def run_frames(self, n):
        time.sleep_us(n * FRAME_US)

    def read_status(self):
        vals = {}
        for _ in range(20000):
            reg = mem32[SIO_GPIO_IN]
            ptr = 0
            for i, gp in enumerate(UO_GPIO):
                ptr |= ((reg >> gp) & 1) << i
            d = 0
            for i, gp in enumerate(UIO_GPIO):
                d |= ((reg >> gp) & 1) << i
            if ptr not in vals:
                vals[ptr] = d
            if len(vals) == 16:
                break
        return {
            "err_cnt": vals.get(0, 0) | (vals.get(1, 0) << 8),
            "gen_cnt": vals.get(2, 0) | (vals.get(3, 0) << 8),
            "mat_cnt": vals.get(4, 0) | (vals.get(5, 0) << 8),
            "ops": vals.get(6, 0) | (vals.get(7, 0) << 8),
            "echo": vals.get(8, 0),
            "stat": vals.get(9, 0),
            "err_dut": vals.get(10, 0),
            "missing": len(set(range(16)) - set(vals.keys())),
        }


def run_case(h, name, word, frames):
    h.configure(word)
    h.run_frames(frames)
    h.freeze(True)
    s = h.read_status()
    h.freeze(False)
    s["case"] = name
    s["word"] = word
    s["frames"] = frames
    emit(s)
    return s


def main():
    for p in (P_RST, P_UICFG):
        Pin(p, Pin.OUT, value=0)
    for p in UIO_PINS:
        Pin(p, Pin.OUT, value=0)
    program()
    cdone = Pin(P_CDONE, Pin.IN).value()
    emit({"case": "program", "cdone": cdone})
    if not cdone:
        return

    h = Harness()
    time.sleep_ms(2)

    run_case(h, "masked_canary",
             cfg_word(pat=1, can=1, win=0, force_can=1), 40)
    run_case(h, "canary_running",
             cfg_word(pat=0, can=1, win=0), 40)
    run_case(h, "force_error_worst",
             cfg_word(seg=(1, 1, 1, 1), pat=1, can=1, win=0,
                      force_can=1, force_err=1), 40)

    # Freeze must hold all measurement state (ops, error count, RO counts).
    h.configure(cfg_word(pat=1, can=1, win=2))
    h.run_frames(20)
    h.freeze(True)
    f1 = h.read_status()
    h.run_frames(10)
    f2 = h.read_status()
    h.freeze(False)
    f1["case"] = "freeze_hold"
    f1["word"] = cfg_word(pat=1, can=1, win=2)
    f1["frozen_ops"] = f2["ops"]
    f1["frozen_err"] = f2["err_cnt"]
    f1["frozen_gen"] = f2["gen_cnt"]
    emit(f1)

    # Reset + reload: counters clear and the new config is committed.
    run_case(h, "reconfigure",
             cfg_word(pat=2, can=2, win=1), 40)

    # Nonzero delay taps exercise the serial ui[7:0] config path (echo byte).
    run_case(h, "taps_echo",
             cfg_word(seg=(3, 2, 1, 0), pat=3, can=1, win=0, force_can=1), 40)

    h.freeze(True)
    return h


if __name__ == "__main__":
    main()
