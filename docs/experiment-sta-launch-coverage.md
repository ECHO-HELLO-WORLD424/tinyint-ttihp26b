# Experiment-STA launch coverage (RTL-freeze gate 4 record)

Scope: `tools/sta/experiment_sta.tcl` + `tools/run_experiment_sta.py`, the
regenerated `data/safe10/` experiment-STA dataset and the prediction package
derived from it. Analysis-only change: **no RTL, constraint, source-list or
floorplan file was touched**, so the physical evidence of build
`0a7cd5e` / run `35034979531` still applies.

Everything below is measured on the archived post-route netlist
`artifacts/run-35034979531/nl/tt_um_echoworld424_tpv.nl.v`
(sha256 `e889762e1fffa169edb4342cc126660965f239c851552ebfc2e57f8d7e11c177`) and
its SPEF (`6675178aedae05319564d33ea05debf40a491f925f7683aa2bd6f1e9eee8384d`)
inside the tool-identical container `ghcr.io/librelane/librelane:3.0.5`
(OpenSTA 2.7.0), unless a statement is explicitly marked as inference.

## Defect

The launch set was discovered by retained net names (`*u_pat.lfsr*`,
`*u_pat.idx*`). Yosys renamed 8 of the 16 LFSR Q nets to auto-generated names
(`_0036_`, `_0037_`, `_0038_`, `_0039_`, `_0040_`, `_0041_`, `_0042_`,
`_0043_` = LFSR bits 0, 5, 6, 7, 10, 11, 13, 15), so only **10 of 18** state
flops were used as `report_checks -from` startpoints. The worst DUT capture
path in the PRBS cases starts at `_1380_` (LFSR bit 13), which was one of the
omitted pins, so the restricted report was optimistic by 0.02-0.09 ns.

## Resolution

`tools/sta/experiment_sta.tcl` now resolves the launch pins structurally,
inside OpenSTA, with net names used only as a cross-check:

1. **Operand seeds** - the 32 preserved `tpv_fa` wrapper input nets
   `*u_dut*g_fa*u_fa.a` / `.b` (4 segments x 4 full adders x 2 operands).
2. **Operand fan-in cone** - backward breadth-first walk through combinational
   cells only, collecting the sequential cells that drive the cone.
3. **Runtime state vs static configuration** - the cone contains 20 flops: the
   18 pattern-generator flops plus `cfg[8]`/`cfg[9]` (`u_pat.sel`), which the
   case loop drives to constants. The 16 case-analyzed `cfg`/`can_sel` nets are
   removed, leaving exactly 18 launch pins.

Assertions enforced in the flow (any failure aborts the run):

- 32 operand seed nets; 18 launch pins; pins unique; every pin a
  sequential-cell output.
- Role recovery without names: the 18 flops must form one 16-node shift chain
  plus a 2-bit counter - exactly one head with four state predecessors whose
  chain indices are `lfsr10/12/13/15` (matching `x^16+x^14+x^13+x^11+1`), 15
  nodes with one predecessor each, one node with no predecessor (`idx0`) and
  one whose only predecessor is `idx0` (`idx1`).
- Every surviving `u_pat.lfsr[N]` / `u_pat.idx[N]` net name must agree with the
  structurally assigned role (10 pins named, 8 renamed).
- The 17 `result_reg` capture endpoints check is unchanged.

Resolved pin list, role map, predecessor counts, the excluded configuration
registers and the per-corner counts are archived in
`data/safe10/experiment_sta_launch_pins.json`.

`tools/sta/verify_launch_coverage.py` re-checks the committed artifacts
without re-running STA (launch set, raw-report traceability, formulas, coverage
classification, control criterion, build hashes); it exits nonzero on any
failure.

## Before / after: restricted vs unrestricted capture path

`ES-R2R` = worst path from the launch set to `result_reg`; `ES-GLOBAL` = worst
path to `result_reg` from any startpoint under the same case analysis. The
table is the PRBS (`pat=0`) subset, where the omission mattered; all 24 rows
(fast/typical/slow x 8 segment configs) changed, the other 72 rows are
unchanged.

| cfg | corner | gap before (ns) | gap after (ns) | R2R startpoint | R2R slack before -> after (ns) |
| --- | --- | --- | --- | --- | --- |
| 0x00FF (seg3333) | fast | -0.030 | 0.000 | `_1379_` (lfsr12) -> `_1380_` (lfsr13) | -0.84 -> -0.87 |
| 0x00FF (seg3333) | typical | -0.060 | 0.000 | `_1379_` -> `_1380_` | -5.73 -> -5.79 |
| 0x00FF (seg3333) | slow | -0.090 | 0.000 | `_1379_` -> `_1380_` | -14.50 -> -14.59 |
| all 8 PRBS configs | fast/typ/slow | -0.020 .. -0.090 | 0.000 (all) | `_1379_` -> `_1380_` | up to 0.09 ns more conservative |

The quoted gate-4 fingerprint (0.03/0.06/0.09 ns at fast/typical/slow) is
exactly the seg3333 gap; after the fix the restricted report is identical to
the unrestricted one in **all 96 cases** (no case where
`global_slack_ns < slack_ns`).

### Classification of unrestricted capture paths (all 96 cases)

| source class | cases | startpoints |
| --- | --- | --- |
| runtime state (one of the 18 launch pins) | 72 | `_1380_` (lfsr13, 24 PRBS cases), `_1383_` (idx0, 48 WORST/ALT cases) |
| control | 24 | `_1334_` (`capture_pending`, all `hold` cases) |
| static configuration | 0 | - |

`hold` case-analyzes the operands to constants, so no runtime-sensitizable path
exists (the R2R report is empty, as before). Its unrestricted worst path is the
`capture_pending` select path into `result_reg` at 9.17/8.86/8.32 ns
(fast/typical/slow) - a control path, not an operand path, and unchanged by
this fix. No static-configuration register (`cfg[*]`, `can_sel[*]`) is the
worst unrestricted startpoint in any case.

## Sensitizing transitions and retained limitations

The recorded per-row operand evidence is a **transition**, not a single
long-carry vector: `sensitizing_prev_vector` -> `sensitizing_vector` at
`sensitizing_op_index`, with the exercised carry chain in
`sensitizing_chain_stages`. The launch edge is the frame-boundary rising edge
(`frame_cnt == FRAME_LAST`, `load = 1`) that advances the pattern register and
sets `capture_pending`; the capture edge is the immediately following falling
edge (clock HIGH time = measurement aperture).

`tools/run_experiment_sta.py::verify_sensitizing_transitions` re-derives each
transition from the RTL decode model (`tools/common.py`) and requires that the
launch register's operand fan-out at that operation meets at least one operand
bit that actually changes between the two vectors - otherwise the path would be
an STA-only structural path. All **72/72** rows with a runtime path pass:

- `lfsr13` (24 PRBS rows): drives `a[0]`, `a[14]`, `b[7]`, `b[9]`; all four
  change on the recorded transition; longest chain 12 stages, endpoint
  `result_reg[16]`.
- `idx0` (48 WORST/ALT rows): drives `b[1..15]` and `cin`; longest chain 17
  stages, endpoints `result_reg[16]` (worst pattern) and `result_reg[0]` (alt).
- `hold` (24 rows): no path, no transition recorded.

Retained limitations (measured facts about the tooling, not inferences):

- Static analysis predicts a structural path; it does not model transition- or
  glitch-dependent delay. The transition check above establishes that an
  applied operand pair can sensitize each reported path, not the silicon delay.
- The SDF cross-check (`tools/run_sdfsim.py`, `data/safe10/sdfsim.csv`)
  annotates cell IOPATH arcs only. Interconnect (wire RC) is not annotated -
  Icarus's interconnect annotator crashes on this design's SDF - and timing
  checks are stripped from the timing-safe library, so failure appears as a
  functional mismatch against the oracle rather than a setup violation. The
  SDF boundary is therefore an approximation with an offset of either sign; the
  SPEF-based extracted STA remains the prediction source. The regenerated
  package keeps the recorded offsets: STA is conservative against the
  IOPATH-only simulation by +1.06 / +1.10 / +2.98 ns at fast/typical/slow.
- `capture_duty = 0.5` is nominal; the real HIGH time must be measured on
  silicon (`docs/prediction-model.md`). Predictions above the 20 ns analyzed
  period are extrapolations of the aperture formula.
- Launch pins are a property of the netlist + case set, not of a corner: the
  flow asserts the resolved list is identical in all three corner runs.

## Oracle / control margin

`control_slack_ns` (worst path ending outside the 17 DUT capture flops) is
positive in all 96 cases; minimum **5.740 ns** at `nom_slow_1p08V_125C`, `alt`.
That minimum is the control path `result_reg[3] -> err_cnt[4]`, not the oracle;
the checker path itself is not the worst control endpoint under this case
analysis. In 24 slow/ALT cases the control path is 1.75 ns *longer* than the
DUT capture path (the ALT workload is carry-free, so its capture path is
short); that does not violate the documented criterion, which is that
`control_slack_ns` stays positive over the claimed envelope - it is positive at
the 20 ns board ceiling and therefore at every slower frequency.

## Regenerated artifacts

Command (host, from the repository root):

```sh
TPV_DATA=data/safe10 python3 tools/run_experiment_sta.py
TPV_DATA=data/safe10 /ttsetup/venv/bin/python3 tools/predict_model.py   # devcontainer
python3 tools/sta/verify_launch_coverage.py --data data/safe10
```

Regenerated: `sta_report_<corner>.txt` (3), `sta_cases_<corner>.tcl` (3,
byte-identical to the previous revision), `experiment_sta.csv/.json`,
`experiment_sta_launch_pins.json` (new), `predict/predictions.csv/.json`,
`predict/summary.md`, `predict/plots.*`.

Inputs and hashes (sha256):

| Artefact | sha256 |
| --- | --- |
| netlist `artifacts/run-35034979531/nl/tt_um_echoworld424_tpv.nl.v` | `e889762e1fffa169edb4342cc126660965f239c851552ebfc2e57f8d7e11c177` |
| SPEF `artifacts/run-35034979531/spef/nom/tt_um_echoworld424_tpv.nom.spef` | `6675178aedae05319564d33ea05debf40a491f925f7683aa2bd6f1e9eee8384d` |
| `tools/sta/experiment_sta.tcl` | `d0e318f807aec4e3bde036f729fd5a30c4068ac70009eb46b61652b9ae9acf5e` |
| `tools/run_experiment_sta.py` | `bc915a9d43f28cbfba186d00190f8802baa63533799ecbff60c5aec472e2b8cd` |
| `tools/common.py` | `d545ac0795ff6f0070d555bb4ad9bc57b7915e3c47a3bae8a68018ae88d2593a` |
| `tools/sta/verify_launch_coverage.py` | `b6e905715ab36e11df11afc5b05f8cf93bc39e9ec3af584d9fb36311b6f40469` |
| `data/safe10/experiment_sta.csv` | `528cb94128ebccf5d3f8e94d3f576a467bd4daec0f90ffeaa00a3a037987b7a7` |
| `data/safe10/experiment_sta.json` | `b243532a323cc98c97e19d30ea665df9ff94cc4a087a22fecbb01f9694b0e36e` |
| `data/safe10/experiment_sta_launch_pins.json` | `5cac6357374f7ce7dae67aff214f0e883f9b9c5a368cd097b4d3e3c12aeb1c5d` |
| `data/safe10/predict/predictions.csv` | `a22f34e9ad0ecc372a160270685a85dc1db244381d5a24402e8a50eca0cd2c0b` |
| `data/safe10/predict/summary.md` | `725054dcedf9f39a7d79d86b633ba81a75e479b846c4e29e683998f7d0af7b0a` |
| `data/safe10/sta_report_nom_fast_1p32V_m40C.txt` | `c5cca7fd21eeee054d7b00116b5786cead84ef92162c9aa7e89014a1732465fe` |
| `data/safe10/sta_report_nom_typ_1p20V_25C.txt` | `3947356626462c439e08ee8d491688848d7c8f8a10defa597a751629d054f13f` |
| `data/safe10/sta_report_nom_slow_1p08V_125C.txt` | `f045a21713bfb2949c3b9b54c0c526fabff92d52932e0571fcfdfa9692b5fae8` |
| `data/safe10/sta_cases_<corner>.tcl` (all three) | `1aa7f5a65f83b91a9fbfa0fe82d82825c187bcd4928e80faf375f10562980237` |

The analysis commit is the commit that adds this record; the physical build
remains `0a7cd5e` / run `35034979531` (no design input changed).

Prediction impact (all in `predict/predictions.csv`): 72 of 288 rows changed -
the 24 PRBS cases in each of the three predictors (`sta`, `ro_gen`, `ro_mat`).
Every changed row moved to a slightly **earlier** boundary, by 0.08-1.40 MHz;
the largest shift is seg0000/fast (135.10 -> 134.00 MHz STA). No non-PRBS row
changed, and no signoff exception, corner or formula was altered.
