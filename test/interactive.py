"""Interactive, cycle-stepped cocotb shell for the TinyInt top-level pins."""

import shlex

import cocotb
from cocotb.triggers import Timer


COMMANDS = {
    "finish": 0b000,
    "clear": 0b001,
    "mac": 0b010,
    "mac_last": 0b011,
    "read": 0b100,
    "load_bias_lo": 0b101,
    "load_bias_hi": 0b110,
    "self_test": 0b111,
}

READ_SELECTORS = {
    "acc_lo": 0b000,
    "acc_mid": 0b001,
    "acc_hi": 0b010,
    "count": 0b011,
    "status": 0b100,
    "product": 0b101,
    "sat": 0b110,
    "id": 0b111,
}

HELP = """Commands:
  show                         display all external pins and decoded controls
  set ui VALUE                 set ui_in[7:0]
  set uio VALUE                set uio_in[7:0]
  set ena VALUE                set ena
  set rst VALUE                set rst_n
  step [COUNT]                 advance COUNT complete clock cycles (default 1)
  reset                        assert reset for two cycles, then release it
  send COMMAND [DATA] [MODE]   accept one protocol command (MODE: 0/1)
  clear signed|unsigned        clear and latch the selected arithmetic mode
  mac ACTIVATION WEIGHT        accept one operand pair (values may be signed)
  last ACTIVATION WEIGHT       MAC the final pair and set done
  finish                       finish without another MAC
  read SELECTOR                read acc_lo/acc_mid/acc_hi/count/status/product/sat/id
  bias VALUE signed|unsigned   load a 16-bit bias and latch the selected mode
  help                         show this help
  quit                         end the simulation

VALUE accepts decimal, 0x hex, 0b binary, or 0o octal. For fully manual use,
set ui/uio and then step; uio bit 0 is cmd_valid, bits 3:1 are the command,
and bit 4 is signed_mode.
"""


def number(text):
    return int(text, 0)


def mode_value(text):
    modes = {"unsigned": 0, "u": 0, "0": 0, "signed": 1, "s": 1, "1": 1}
    try:
        return modes[text.lower()]
    except KeyError as exc:
        raise ValueError("mode must be signed/unsigned or 1/0") from exc


def named_or_number(text, names):
    name = text.lower()
    return names[name] if name in names else number(text)


def signal_int(signal):
    return int(signal.value)


def show(dut, cycle):
    ui = signal_int(dut.ui_in)
    uio_in = signal_int(dut.uio_in)
    uo = signal_int(dut.uo_out)
    uio_out = signal_int(dut.uio_out)
    uio_oe = signal_int(dut.uio_oe)
    print(
        f"cycle={cycle:<5} clk={signal_int(dut.clk)} rst_n={signal_int(dut.rst_n)} "
        f"ena={signal_int(dut.ena)}\n"
        f"  inputs : ui_in=0x{ui:02x} ({ui:08b})  "
        f"uio_in=0x{uio_in:02x} ({uio_in:08b})\n"
        f"  outputs: uo_out=0x{uo:02x} ({uo:08b})  "
        f"uio_out=0x{uio_out:02x} ({uio_out:08b})  uio_oe=0x{uio_oe:02x}\n"
        f"  decoded: valid={uio_in & 1} cmd={(uio_in >> 1) & 7:03b} "
        f"mode={(uio_in >> 4) & 1} | ready={(uio_out >> 5) & 1} "
        f"response_valid={(uio_out >> 6) & 1} busy={(uio_out >> 7) & 1}",
        flush=True,
    )


async def step_cycle(dut, cycle):
    dut.clk.value = 0
    await Timer(5, unit="ns")
    dut.clk.value = 1
    await Timer(1, unit="ns")
    cycle += 1
    show(dut, cycle)
    await Timer(4, unit="ns")
    dut.clk.value = 0
    return cycle


async def send_command(dut, cycle, command, data=0, mode=None):
    if mode is None:
        mode = (signal_int(dut.uio_in) >> 4) & 1
    dut.ui_in.value = data & 0xFF
    dut.uio_in.value = ((mode & 1) << 4) | ((command & 7) << 1) | 1
    cycle = await step_cycle(dut, cycle)
    dut.uio_in.value = (mode & 1) << 4
    return cycle


@cocotb.test()
async def interactive(dut):
    """Run a REPL in which simulation time advances only on explicit commands."""
    dut.clk.value = 0
    dut.rst_n.value = 0
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    cycle = 0

    # Start from deterministic architectural state. Stateful outputs are X in
    # RTL until at least one clock edge occurs while reset is asserted.
    await Timer(1, unit="ps")
    print("\nTinyInt interactive simulator. Type 'help' for commands.\n", flush=True)
    cycle = await step_cycle(dut, cycle)
    cycle = await step_cycle(dut, cycle)
    dut.rst_n.value = 1
    await Timer(1, unit="ps")
    show(dut, cycle)

    while True:
        try:
            words = shlex.split(input("tinyint> "))
            if not words:
                continue
            command = words[0].lower()

            if command in {"quit", "exit", "q"}:
                break
            if command in {"help", "?"}:
                print(HELP, flush=True)
            elif command == "show":
                show(dut, cycle)
            elif command == "set":
                if len(words) != 3:
                    raise ValueError("usage: set ui|uio|ena|rst VALUE")
                target, value = words[1].lower(), number(words[2])
                signals = {
                    "ui": dut.ui_in,
                    "uio": dut.uio_in,
                    "ena": dut.ena,
                    "rst": dut.rst_n,
                }
                if target not in signals:
                    raise ValueError("target must be ui, uio, ena, or rst")
                signals[target].value = value
                show(dut, cycle)
            elif command == "step":
                count = number(words[1]) if len(words) == 2 else 1
                if len(words) > 2 or count < 1:
                    raise ValueError("usage: step [positive count]")
                for _ in range(count):
                    cycle = await step_cycle(dut, cycle)
            elif command == "reset":
                dut.ui_in.value = 0
                dut.uio_in.value = 0
                dut.rst_n.value = 0
                cycle = await step_cycle(dut, cycle)
                cycle = await step_cycle(dut, cycle)
                dut.rst_n.value = 1
                show(dut, cycle)
            elif command == "send":
                if not 2 <= len(words) <= 4:
                    raise ValueError("usage: send COMMAND [DATA] [MODE]")
                opcode = named_or_number(words[1], COMMANDS)
                data = number(words[2]) if len(words) >= 3 else 0
                mode = mode_value(words[3]) if len(words) == 4 else None
                cycle = await send_command(dut, cycle, opcode, data, mode)
            elif command == "clear":
                if len(words) != 2:
                    raise ValueError("usage: clear signed|unsigned")
                cycle = await send_command(
                    dut, cycle, COMMANDS["clear"], mode=mode_value(words[1])
                )
            elif command in {"mac", "last"}:
                if len(words) != 3:
                    raise ValueError(f"usage: {command} ACTIVATION WEIGHT")
                activation, weight = number(words[1]), number(words[2])
                data = ((activation & 0xF) << 4) | (weight & 0xF)
                opcode = COMMANDS["mac_last" if command == "last" else "mac"]
                cycle = await send_command(dut, cycle, opcode, data)
            elif command == "finish":
                if len(words) != 1:
                    raise ValueError("usage: finish")
                cycle = await send_command(dut, cycle, COMMANDS["finish"])
            elif command == "read":
                if len(words) != 2:
                    raise ValueError("usage: read SELECTOR")
                selector = named_or_number(words[1], READ_SELECTORS)
                cycle = await send_command(dut, cycle, COMMANDS["read"], selector)
            elif command == "bias":
                if len(words) != 3:
                    raise ValueError("usage: bias VALUE signed|unsigned")
                value, mode = number(words[1]) & 0xFFFF, mode_value(words[2])
                cycle = await send_command(
                    dut, cycle, COMMANDS["load_bias_lo"], value & 0xFF, mode
                )
                cycle = await send_command(
                    dut, cycle, COMMANDS["load_bias_hi"], value >> 8, mode
                )
            else:
                raise ValueError(f"unknown command: {command!r}; type 'help'")
        except EOFError:
            print("\nEnd of input; stopping simulation.", flush=True)
            break
        except (ValueError, OverflowError) as exc:
            print(f"error: {exc}", flush=True)
