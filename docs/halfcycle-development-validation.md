# Half-cycle development implementation and verification

> **Merged (2026-09-08):** the design verified here was fast-forward merged
> into `proposal-canary` (tip `a35f501`). This page is preserved as the
> development-time record; the branch, clock and signoff statements below
> describe the intermediate 50 MHz development candidate and are superseded
> by the 10 MHz normal-operation specification
> ([attempt log](ci-timing-closure-attempts.md)). The 60% area objective
> referenced below was later retired by owner decision; approximately 70%
> utilization is accepted for the merged candidate.

Branch: **proposal-canary-dev** (development record; the original
`proposal-canary` reference at the time was
`96811e87dc11fdbb70785de9b84abc879ca3155d` and no changes were committed
there before the merge).
Final physical input revision: **041c1906a276211a62263dc30ce0da13b01c00ed**.
The subsequent analysis/documentation commit does not change those RTL or
constraint inputs; the local manifest verifies their file contents against this
revision. This is local development evidence, not a GitHub Actions result.

## Implementation

- Launch operands on the frame-boundary rising edge; a registered
  `capture_pending` pulse captures the DUT on the immediately following falling
  edge. The result holds until comparison. No clock gating or delayed clock
  generator was introduced.
- FREEZE blocks launches but permits an already accepted half-cycle sample to
  finish. `capture_pending` clears even during freeze, preventing deferred or
  repeated sampling on resume. Read after two full clocks of settling.
- Replace the serial checker with a separate combinational reference adder.
  Operands stay stable for the frame; comparison is at the next boundary.
- Capture stable configuration pins directly at the third rising edge, removing
  the duplicate 16-bit shadow register. Share the boot state with uio direction
  control and narrow the window counter from 16 to 14 bits.
- Implement true 16-bit ripple RO counters. Only the least-significant bit sees
  the full oscillator frequency; higher bits toggle on preceding falling edges.
  Counters retain their modulo-65536 behavior and byte map.
- Retain the 1x1 tile, 50 MHz submitted maximum, 19-cycle frame, four bank taps,
  both physical RO loops, FORCE_ERR/FORCE_CAN, and saturating error/op counters.
- Make the 50% clock waveform explicit in SDC. Signoff uncertainty, IO constraints
  and setup checking remain intact. Update STA conversion to T_boundary = T − S/d.

## Final results

| Check | Result |
| --- | --- |
| RTL cocotb | 13 pass, 0 fail |
| Functional GL | 9 pass, 0 fail, 4 intentional RTL-only skips |
| Tiny Tapeout precheck | 10 pass |
| Routing DRC / Magic DRC / LVS / antenna | 0 violations/errors |
| Max slew / max capacitance | 0 violations |
| Hold slack fast / typical / slow | +0.1315 / +0.2189 / +0.3769 ns |
| Worst case-analyzed control setup slack, 50 MHz | +6.26 ns |
| Final active standard-cell area | 20,990.8 µm² |
| Final utilization | **72.5284%**, versus original 82.86% |
| Active area saving | 2,990.1 µm², about **12.47%** |
| Sequential cells | 152, versus original 195 |
| Structural checks | All 384 DUT bank inverters/taps; both closed RO loops; 17 falling captures |

The configured placement density is 72%; actual final utilization is 72.53%.
The first routed candidate without ripple counters used 74.08%; the final
candidate includes the additional counter saving. Neither result reaches 60%:
**another 3,625.9 µm²**, about 17.27% of the new active area, would have to be
removed to reach that target in the existing core. This is an improvement, not
closure of the original utilization concern.

### Observable timing boundary

Case-analyzed, extracted seg3333/worst results:

| Corner | STA boundary | IOPATH-only SDF: last fail / first pass |
| --- | ---: | ---: |
| Fast, 1.32 V, −40 °C | 45.126 MHz | 20 / 22 ns period |
| Typical, 1.20 V, 25 °C | **30.998 MHz** | **32 / 34 ns period** |
| Slow, 1.08 V, 125 °C | 19.904 MHz | 46 / 48 ns period |

At nominal conditions, the SDF boundary is between 29.412 and 31.25 MHz at
50% duty. The maximum-tap worst-case workload produces 49 errors in 199 completed
comparisons at a failing point; the launch counter reads 200. Other configurations
can remain above the clock ceiling and must be reported as censored.

The aperture check reruns extracted STA at periods 20/40 ns and duties
0.4/0.5/0.6, confirming invariant required HIGH time. Timed simulation compares
14 ns HIGH (failure) and 18 ns HIGH (pass) at all three duties; equal high times
produce equal deterministic error counts. Additional nominal timed controls pass:
PRBS at 40 ns and ALT/HOLD at 20 ns period. The half-cycle boundary is supported
at the typical ambient library point without a 125 °C requirement. Actual die
process, clock delivery and temperature are still unmeasured.

### Signoff status: deliberately not hidden

LibreLane completes layout/extraction/physical checks and saves final views,
then exits **1** because the unchanged 20 ns, 50%-duty setup check fails at the
typical corner. Global setup slacks fast/typical/slow are
−1.1844 / −6.2859 / −15.3976 ns. The experiment deliberately gives the DUT only
10 ns at 50 MHz; a DUT that starts failing near 31 MHz necessarily violates that
setup requirement at maximum delay.

The generic setup failure is **not waived**, and no multicycle/false-path
exception hides it. The separately case-analyzed synchronous control envelope
has positive slack. Consequently this branch is a verified experimental candidate,
**not an all-green submission build**. A submission-compatible timing policy
must be agreed separately; accepting the local physical result does not certify
50 MHz error-free DUT operation. The 60% area target is also still open.

## Verification details and provenance

RTL tests cover one-shot falling capture, no rising capture, freeze inside the
aperture, every frame phase's freeze/resume, reset/reconfiguration, config echo,
first-error accounting, counter saturation, RO wrap and reset, and all workloads.
GL checks use the newly routed netlist; four tests needing internal RTL access
or live simulation-only RO delays are intentionally skipped.

The GL run initially exposed a testbench reset/clock race: reset was deasserted
exactly at the first counted rising edge. Releasing reset during LOW before the
first counted edge fixes the stimulus and agrees with the timed testbench and
physical recovery requirements. No RTL or timing constraint was changed to mask
that failure. Both RTL and GL were rerun with the corrected helper.

The design hardened using **LibreLane 3.0.5**, image
`ghcr.io/librelane/librelane:3.0.5`, PDK revision
`c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c`, support-tools revision
`01d5d2814fa9dd61e9d211e0b235a4a592a9316a`.
The devcontainer's separate installed LibreLane 3.0.0.dev44 was not used to
produce these physical results. Precheck used existing devcontainer Python
packages and KLayout from the pinned image; package versions/image identities
are recorded in `data/halfcycle/verification/local-build-manifest.json`.

The SDF sweep omits interconnect and flip-flop timing checks; it does not model
metastability or establish silicon error probabilities. RO estimates use the
regenerated extracted broken-loop model (24 rows), not transient SPICE. Physical
LVS plus named connectivity checks support preservation; they do not validate
absolute RO frequency or the final board's allowable thermal range.

## Reproduction

Run from the repository root **inside the devcontainer**. Physical views are in
ignored `src/runs/dev-halfcycle-final/`; they are retained locally and hashed by
the committed manifest, rather than added as another large binary archive.

```sh
source /ttsetup/venv/bin/activate
python tt/tt_tool.py --ihp --create-user-config
# Harden through the pinned image, using the support-tools merged configuration:
docker run --rm -v /workspaces/tinyint-ttihp26b:/work \
  -v /home/vscode/ttsetup/pdk:/pdk:ro -w /work \
  ghcr.io/librelane/librelane:3.0.5 python3 -m librelane \
  --manual-pdk --pdk-root /pdk/ciel/ihp-sg13g2/versions/c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c \
  --pdk ihp-sg13g2 --run-tag dev-halfcycle-final --jobs 8 --condensed src/config_merged.json
# Expected exit 1 at setup checking; inspect the saved final reports.

# RTL / GL: run separately and inspect results.xml after each.
(cd test && make clean && make)
cp src/runs/dev-halfcycle-final/final/nl/tt_um_echoworld424_tpv.nl.v test/gate_level_netlist.v
(cd test && make clean && PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c make GATES=yes)

python3 tools/run_local_precheck.py
python3 tools/run_experiment_sta.py
python3 tools/run_ro_predict.py
python3 tools/sdf/make_sdf_lib.py
python3 tools/run_sdfsim.py
python3 tools/verify_halfcycle.py
python3 tools/verify_halfcycle_structure.py
python3 tools/predict_model.py
# Preserve the RTL/GL XML files under data/halfcycle/verification before:
python3 tools/make_manifest.py
```

Use a fresh run tag or LibreLane's explicit overwrite option if rebuilding.
Changing the tag requires updating the local view path/build identity in
`tools/common.py`. Run manifests must continue to distinguish source, analysis
and tool revisions, and must not be labeled as CI or tapeout approval.
