## How it works

TinyInt is a streaming INT4 dot-product design built around an original shared
unsigned/Baugh-Wooley signed multiplier. The current multiplier-baseline core
owns a latched operating mode; normal multiplication never reads the live mode
pin directly.

## How to test

After reset, unsigned mode is active. To select a transaction mode, present
command `001` on `uio_in[3:1]`, the desired signed mode on `uio_in[4]`, and
assert `uio_in[0]` for an accepted rising clock edge. Place the weight on
`ui_in[3:0]` and activation on `ui_in[7:4]`; the current multiplier-baseline
product appears on `uo_out`.

## External hardware

None.
