# Frozen pre-silicon prediction protocol

Model version: **`tpv-predict-1.0.1`**. This document is the protocol fixed
before any silicon measurement. Predictor definitions, the calibration
equations, thresholds, and metrics below may only change by publishing a new
model version *before* post-silicon data is examined; after silicon arrives,
the only permitted change is substituting measured values into the calibration
factor (and the measured ground truth). Generated outputs: `data/predict/`
(`tools/predict_model.py`). Field units and RTL mirrors:
`docs/data-dictionary.md`.

Revision history: `1.0.0` first frozen revision; `1.0.1` (still pre-silicon)
adds the `1e-6`/op threshold as a scored boundary, predeclares the anchor
fallback `A'` and censoring contingency (the nominal anchor may be
unreachable on the board), and corrects the canary-counter semantics (16-bit
wrap, not saturation) — see `docs/post-silicon-protocol.md`.

## Inputs (pinned)

- `data/experiment_sta.csv` (96 rows), `data/ro_predict.csv` (24 rows),
  `data/sdfsim.csv` — all regenerated against hardening run `33839023290`,
  commit `1e31757e50080b19fa7642b8b9cd6822f64b1d11`, LibreLane image
  `ghcr.io/librelane/librelane:3.0.5`, PDK ciel revision
  `c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c`. The model script asserts this
  provenance is constant across all inputs.
- Conventions: 19-cycle frames; 16-bit canary counters that WRAP mod 65536
  (telemetry; only `err_cnt`/`ops_cnt` saturate in hardware); window win =
  `2^(8+2*win)` clk cycles; nominal corner `nom_typ_1p20V_25C`;
  predeclared canary readout **can_sel = 3, win0** (256 clk cycles).

## Ground truth (post-silicon first-failure boundary)

An operating point (corner, seg config, pattern, period `T`) FAILS iff
`err_cnt >= 1` is observed over the run (`N_ops >= 200`; larger `N_ops` on
silicon, recorded per point). Primary boundary threshold: first error.
Secondary thresholds `err_rate >= 1e-6`, `1e-4`, and `1e-2` per op are
recorded and scored (boundary extraction and metrics computed per
threshold); calibration uses the primary first-error threshold only.
Threshold boundaries are extracted per `docs/post-silicon-protocol.md`
(bracket midpoint, per-threshold).

Sweep protocol: frequency up then down; a point's bracket is
`[last failing period, first passing period]`. The measured boundary is the
bracket midpoint:

    T_meas = (T_last_fail + T_first_pass) / 2      [ns]
    F_meas = 1000 / T_meas                          [MHz]

## Predictors (frozen definitions)

Let `nom = nom_typ_1p20V_25C` and `N_x(c)` = canary `x` edge count at the
readout config (can_sel 3, win0) at corner `c`.

1. **P_STA** (uncalibrated extracted STA):

       P_STA(cfg, pat, c) = 1000 / (T_clk - slack(cfg, pat, c))   [MHz]

   with `slack` from the case-analyzed runtime path (`u_pat -> result_reg`)
   at corner `c` and analysis point `T_clk = 20 ns`; per-corner linear
   translation of slack, clock tree/uncertainty held at the corner.

2. **P_GEN** (generic-RO canary):

       P_GEN(cfg, pat, c) = P_STA(cfg, pat, nom) * N_gen(c) / N_gen(nom)

3. **P_MAT** (structure-matched-RO canary):

       P_MAT(cfg, pat, c) = P_STA(cfg, pat, nom) * N_mat(c) / N_mat(nom)

Both canary predictors are **monotone maps from canary count to predicted DUT
first-failure frequency** (higher count = faster silicon = higher predicted
boundary; equivalently in the period domain `T_x = T_STA(nom) * N_x(nom) /
N_x(c)`). They are built ONLY from nominal-corner structure: the nominal STA
ladder provides the configuration/workload dependence, the canary count ratio
provides the PVT tracking. At `c = nom` all three predictors equal the
nominal STA ladder by construction. With only three PVT corners available
pre-silicon, **no free parameters are fitted** to corner data; the model may
be judged on corner-wise rank correlation but nothing is fitted per point.

Consequence, stated up front: because the canary predictors are anchored to
the nominal STA ladder, `P_STA = P_GEN = P_MAT` at nominal; the predictors
differ only through their corner scaling, and all three one-point calibration
factors coincide numerically at the anchor. Predictor merit is therefore
evaluated at non-nominal corners and across configurations, never at the
anchor itself.

## One-point calibration (predeclared)

Primary anchor `A = (1.20 V, 25 °C, seg3333, pattern = worst)`, measured on
the same die at the same readout config. The nominal seg3333/worst knee is
predicted at 61.46 MHz, above the 50 MHz board ceiling, so `A` may be
unmeasurable on the board. Predeclared fallback, applied in order without
examining any other boundary data:

- `A' = (1.08 V, maximum reachable temperature, seg3333, pattern = worst)`
  (matched to the slow corner, predicted knee 39.34 MHz — inside range);
  when `A'` is used, the calibration ratio is defined in the PERIOD domain
  against the slow-corner predictions and the die temperature is recorded
  with the point.
- If neither `A` nor `A'` is reachable (no voltage/temperature control),
  calibration is censored: report uncalibrated metrics only and state the
  censoring explicitly in the results.

For each predictor `x` at the measured anchor:

    k_x   = F_meas(A) / P_x(A)          [dimensionless, one per predictor]
    P_x_cal(cfg, pat, c) = k_x * P_x(cfg, pat, c)     (everywhere, unchanged)
    T_x_cal(cfg, pat, c) = T_x(cfg, pat, c) / k_x     (period domain)

Pseudocode (the selected anchor is primary `A`, otherwise the predeclared `A'`):

```
anchor = primary_anchor_if_measurable_else_fallback_A_prime
for x in ["sta", "ro_gen", "ro_mat"]:
    F_pred_anchor = predict(x, corner=anchor.corner,
                            segs=3333, pattern="worst")
    k[x] = F_meas_anchor / F_pred_anchor  # single measured division
    for (corner, segs, pat) in measurement_matrix:
        P_cal = k[x] * predict(x, corner, segs, pat)
        emit(x, corner, segs, pat, P_cal)
```

`data/predict/predictions.csv` already contains the placeholder rows
(`cal_k = 1.0`, `*_cal = uncalibrated`); the post-silicon run substitutes the
measured `k_x` values and nothing else. At the nominal anchor the three
`k_x` coincide numerically at pre-silicon; they are still emitted
per-predictor so the anchor definition can move without redefining the model.

## Post-silicon evaluation metrics (predeclared)

For each measured point with calibrated prediction `P_cal` and measured
boundary `F_meas`:

- **Boundary error**: `e_abs = P_cal - F_meas` [MHz] and
  `e_rel = (P_cal - F_meas) / F_meas` [%]; positive = overprediction
  (missed-failure risk).
- **Guardband rule**: an operating frequency `f_op` is declared safe iff
  `f_op <= P_cal * (1 - g)`.
- **Missed-failure rate**: fraction of measured failing points declared safe.
- **False-warning rate**: fraction of measured passing points declared unsafe.
- **Required guardband** `g*`: minimum `g` achieving zero missed failures on
  the measured sweep; **guardband cost** = `g*` (fraction of predicted
  boundary frequency unused), also reported as `g* * P_cal` [MHz].
- **Rank correlation**: Spearman rank correlation between `P_cal` and
  `F_meas` across all measured (cfg x pat x corner) boundary points.
- **Workload dependence**: `e_rel` compared across patterns (prbs, worst,
  alt; hold excluded by construction).
- **Calibration benefit**: identical metrics computed uncalibrated vs
  calibrated; the delta is the reported value of one-point calibration.

## Known limitations (part of the protocol, not footnotes)

- The STA knee is a linear slack translation; validity degrades far from the
  20 ns analysis point.
- The SDF boundary is IOPATH-only annotated (wire interconnect unannotated;
  Icarus's interconnect annotator crashes on this design), so the sim is
  optimistic by ~1.3-3.4 ns vs STA (`data/predict/summary.md` cross-check).
- The `sdfsim.csv` RO cross-check row (FORCE_CAN off) is INVALID: RO loop
  cells carry hard 0.000 SDF delays because `src/pnr.sdc` disables RO timing
  arcs (`docs/ro-sdf-crosscheck-diagnosis.md`). Its counts are excluded from
  this model.
- `alt` knees lie above the 50 MHz board ceiling (not measurable there);
  `hold` has no runtime path (no prediction by construction).
- Canary counts are floor-quantized (+-1 edge); at win0 counts >= 240 the
  ratio quantization is <= ~0.4%.
- Canary counters wrap mod 65536 (no saturation flag in hardware); at the
  predeclared readout (can_sel 3, win0) all counts fit without wrapping.
  Larger windows require host-side unwrapping per
  `docs/post-silicon-protocol.md`.
- One die: all claims are within-die PVT/workload validation, not process
  distribution.

## model_version

`tpv-predict-1.0.1` — current frozen revision. Bumping the version requires a
revised pre-declaration committed before silicon data is examined.
