## How it works

TinyInt is a streaming INT4 dot-product design built around an original shared
unsigned/Baugh-Wooley signed multiplier. The current core owns a latched
operating mode; normal multiplication never reads the live mode pin directly.
It sign- or zero-extends the raw product to the accumulator's 20-bit input. A
separate 20-bit modulo accumulator leaf provides clear, load,
accumulate, and hold controls plus sticky signed/unsigned overflow detection
for the upcoming command-controller integration.

## How to test

After reset, unsigned mode is active. To select a transaction mode, present
command `001` on `uio_in[3:1]`, the desired signed mode on `uio_in[4]`, and
assert `uio_in[0]` for an accepted rising clock edge. Place the weight on
`ui_in[3:0]` and activation on `ui_in[7:4]`; the current multiplier-baseline
product appears on `uo_out`.

## External hardware

None.
