![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# TinyInt

![TinyInt target architecture](./chip-architecture.svg)

TinyInt is a 1 x 1 Tiny Tapeout research vehicle for comparing a conventional
20-bit accumulator with a bit-exact dynamic accumulator behind the same
signed/unsigned INT4 multiplier. The dynamic state is divided into five 4-bit
stages. Software selects an 8-, 12-, or 16-bit active boundary; higher stages
update only when a carry or borrow crosses that boundary. Every mode retains
the same full 20-bit modulo result.

The RTL implements both accumulator architectures, their isolated mode mux,
the complete command/readback protocol, and the tapeout wrapper. The frozen
architecture, protocol, verification gates, and measurement method are in the
[project specification](project-description.md). The literature review and
research plan are in the [research proposal](research-proposal.md).

## Interface

- `ui_in[3:0]`: operand B during `MAC`
- `ui_in[7:4]`: operand A during `MAC`
- `uio_in[4]`: signed mode, sampled by `CLEAR`
- `uio_in[3:1]`: command (`000` `FINISH`, `001` `CLEAR`, `010` `MAC`,
  `011` `MAC_LAST`, `100` `READ`)
- `uio_in[0]`: command valid
- `uio_out[5]`: ready
- `uio_out[6]`: registered response valid
- `uio_out[7]`: busy, reserved low
- `uo_out[7:0]`: registered read response

`CLEAR` also latches its payload: `ui_in[1:0]` selects conventional,
dynamic-8, dynamic-12, or dynamic-16, and `ui_in[2]` enables exact zero-product
skipping. `ui_in[7:3]` must be zero during `CLEAR`. The physical pinout is
unchanged from the baseline.

## Architecture

```mermaid
flowchart LR
    HOST["Tiny Tapeout pins<br/>commands, operands, configuration"]
    PROTO["Protocol and mode latch"]
    MUL["Shared 4 x 4<br/>signed/unsigned multiplier"]
    EXT["8-to-20-bit<br/>sign/zero extension"]
    SEL{"Latched accumulator mode"}
    BASE["Conventional<br/>20-bit adder/register"]
    DYN["Dynamic accumulator<br/>five 4-bit stages<br/>boundary 8 / 12 / 16"]
    READ["Selected-state readback<br/>status and diagnostics"]

    HOST --> PROTO --> MUL --> EXT --> SEL
    SEL -->|mode 00| BASE
    SEL -->|modes 01-11| DYN
    BASE --> READ
    DYN --> READ
    READ --> HOST
```

The nonselected accumulator is operand-isolated and state-disabled. The
provided synthesis scripts generate baseline-only and dynamic-only builds with
identical constraints for uncontaminated comparison; the composite tapeout
enables same-die active-energy A/B measurements.

## Verification

Run the full RTL Cocotb regression with:

```sh
make test=ALL
```

The repository also contains exhaustive one-step dynamic-accumulator tests,
formal arbitrary-stream equivalence, randomized protocol/model tests,
standalone/composite synthesis checks, and post-layout gate regression. Every
command and result used for release verification is recorded in
[`TEST_LOG.md`](TEST_LOG.md). The same architectural vectors can be reused
post-silicon through the Tiny Tapeout SDK or `microcotb`.

The final IHP SG13G2 implementation fits one 1x1 tile at 50 MHz and is clean in
route DRC, Magic DRC, KLayout DRC, Netgen LVS, antenna, setup, and hold checks.
The reusable activity flow and standalone comparison scripts are documented in
[`synthesis/README.md`](synthesis/README.md).

## Tiny Tapeout

Tiny Tapeout makes it practical to manufacture small digital and mixed-signal
designs. See the [Tiny Tapeout documentation](https://tinytapeout.com/) and the
[local hardening guide](https://www.tinytapeout.com/guides/local-hardening/).
