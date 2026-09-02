## How it works

TinyInt is an INT4 MAC research tapeout. A shared signed/unsigned 4 x 4
Baugh-Wooley multiplier feeds either a conventional 20-bit accumulator or a
bit-exact dynamic accumulator divided into five 4-bit stages. At transaction
start, software selects a conventional mode or an 8-, 12-, or 16-bit dynamic
boundary. Cold stages update only when a carry or borrow crosses the selected
boundary; no accumulator bits are truncated.

The current repository RTL implements the conventional baseline. The dynamic
path and its new configuration/readback behavior are the frozen next
implementation milestone described in `project-description.md`.

## How to test

All signals are synchronous to `clk`. Assert `cmd_valid` on `uio_in[0]` while
`ready` on `uio_out[5]` is high. Commands are carried on `uio_in[3:1]`:

- `001`: `CLEAR` and latch configuration
- `010`: `MAC`
- `011`: `MAC_LAST`
- `000`: `FINISH`
- `100`: `READ`

During `CLEAR`, `ui_in[1:0]` selects conventional, dynamic-8, dynamic-12, or
dynamic-16; `ui_in[2]` enables zero-product skipping; and `uio_in[4]` selects
unsigned or signed arithmetic. Drive `ui_in[7:3]` low. During a MAC, place
operand B on `ui_in[3:0]` and operand A on `ui_in[7:4]`.

For `READ`, selectors `000`--`010` return the three accumulator bytes; `011`
returns pair count; `100` status; `101` last product; `110` latched
configuration; and `111` design ID. `uo_out` is valid in the cycle marked by
`uio_out[6]`.

The pre-silicon suite will exhaust the multiplier and boundary transition
spaces, formally prove conventional/dynamic equivalence for arbitrary streams,
and run randomized command traces. Those vectors will be reused on silicon.

## External hardware

Normal functional testing requires only the Tiny Tapeout demo board. Power
measurement needs external instrumentation because the demo board has no
documented current sensor. On the IHP breakout, the removable `R4` 0-ohm link
between `VCORE_REG` and `VDD_CORE` provides a location for an external shunt
and differential amplifier or a source-measure unit.
