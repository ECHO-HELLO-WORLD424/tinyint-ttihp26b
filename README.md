![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# Timing-Prediction Test Vehicle

A 1x1 Tiny Tapeout `ttihp26b` chip for comparing pre-silicon timing
predictions and on-chip delay proxies with post-silicon arithmetic
first-failure boundaries in IHP SG13G2.

## Architecture

- **DUT:** a structurally preserved 16-bit ripple-carry adder with four
  independently selectable inverter-pair delay banks.
- **Oracle:** a short-path bit-serial reference adder that checks one captured
  result per 19-cycle frame.
- **Canaries:** a generic inverter ring oscillator and a structure-matched
  ring oscillator, each with a 16-bit wrapping edge counter.
- **Measurement:** saturating error/operation counters, first-error capture,
  freeze-before-readout, serial status bytes, and `FORCE_ERR`/`FORCE_CAN` DFT.

The contribution is experimental quantification rather than a new canary
architecture: case-analyzed extracted STA, a generic RO, and a matched RO are
evaluated as predictors of the measured workload-dependent DUT boundary.

## Current state

The pre-silicon package is complete for hardware revision
`1e31757e50080b19fa7642b8b9cd6822f64b1d11` and hardening run
[`33839023290`](https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/33839023290):

- 10/10 RTL cocotb tests pass.
- The zero-delay functional GL suite has 8 passes and 2 intentional skips.
- Tiny Tapeout precheck, GDS, GL, and viewer jobs pass.
- DRC, Magic DRC, LVS, antenna, and power-grid checks are clean; hold slack is
  positive at all reported corners.
- The committed prediction package contains 96 runtime case-analyzed STA
  cases, 24 broken-loop extracted RO cases, 13 SDF probe rows, and 288 joined
  predictor rows.
- Final GDS/netlist/SPEF/SDF/SDC/DEF files and hashes are archived under
  `artifacts/run-33839023290/`.

The current RO estimate is a parasitic-aware broken-loop static model, not a
transient SPICE simulation. The post-silicon voltage range is also contingent
on the Tiny Tapeout board power topology. Both limitations are explicit parts
of the frozen protocol.

## Documentation

- [Datasheet and chip protocol](docs/info.md)
- [Research question and design rationale](docs/research-proposal.md)
- [Pre-silicon status and evidence](PRE_SILICON_ACTION_PLAN.md)
- [Frozen prediction model](docs/prediction-model.md)
- [Frozen post-silicon protocol](docs/post-silicon-protocol.md)
- [Dataset field definitions](docs/data-dictionary.md)
- [Final build manifest](artifacts/run-33839023290/MANIFEST.md)

## Verification

Use the repository devcontainer for HDL and physical-design work.

```sh
cd test
make clean
make
```

For the functional GL test, first copy the archived final netlist:

```sh
cp artifacts/run-33839023290/nl/tt_um_echoworld424_tpv.nl.v test/gate_level_netlist.v
cd test
make clean
make GATES=yes
```

The experiment-specific tools are:

```sh
python3 tools/run_experiment_sta.py
python3 tools/run_ro_predict.py
python3 tools/run_sdfsim.py
python3 tools/predict_model.py
python3 tools/make_manifest.py
```

The STA, RO, and SDF drivers require the pinned LibreLane/PDK environment
described in [AGENTS.md](AGENTS.md). Do not mix locally generated physical
metrics with CI results without recording their provenance.

## Tiny Tapeout

Tiny Tapeout makes small open-source ASIC fabrication accessible. Project and
board documentation are available at <https://tinytapeout.com/>.
