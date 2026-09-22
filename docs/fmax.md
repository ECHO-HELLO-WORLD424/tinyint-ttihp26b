# Maximum operating frequency (Fmax)

This note defines how the top clock frequency of the hardened TinyInt design is
measured and what the result means. The flow is `synthesis/run_fmax_sweep.sh`
driving `synthesis/fmax_sweep.tcl` through the pinned LibreLane OpenSTA image.

## Why timing analysis, not simulation

TinyInt is a single-clock synchronous design. Its failure at high frequency is a
setup-time violation: data launched by one register cannot reach the next before
the capture edge. RTL simulation and zero-delay functional gate simulation model
no cell or wire delay, so they pass at any clock period and cannot find Fmax.
Fmax must come from static timing analysis (STA) on the routed netlist with
extracted parasitics, optionally cross-checked later by SDF-annotated gate-level
simulation.

## Method

1. Read the routed netlist `runs/wokwi/final/nl/*.nl.v`, the nominal extracted
   `runs/wokwi/final/spef/nom/*.nom.spef`, the released SDC
   `runs/wokwi/final/sdc/*.sdc`, and the corner liberty (SG13G2 standard cells).
2. Redefine `create_clock -name clk -period <P> [get_ports clk]` and re-apply the
   released `set_clock_transition 0.15`, `set_clock_uncertainty 0.25`, and
   `set_propagated_clock` constraints. The propagated clock and SPEF make the
   measured slack include real clock latency and skew.
3. Coarse scan from `CLK_START` to `CLK_STOP` in `CLK_STEP` steps to bracket the
   first period with negative worst setup slack, then binary-search to `CLK_TOL`.
4. Report `Fmax = 1 / period_fail` per corner. The design limit is the minimum
   across corners because setup is worst at the slow corner.

Run:

```sh
PDK_ROOT=/path/to/ihp-sg13g2/version \
  sh synthesis/run_fmax_sweep.sh
```

Useful overrides: `CORNERS`, `CLK_START`, `CLK_STOP`, `CLK_STEP`, `CLK_TOL`,
`LIBRELANE_IMAGE`.

Outputs land in `test/sim_build/fmax/`:

- `<corner>/fmax_<corner>.log`: every `FMAX_POINT`, the `FMAX_RESULT`, and the
  worst setup path (`report_checks -path_delay max`) at the failing period.
- `fmax_summary.csv`: `corner,status,period_fail_ns,fmax_mhz,wns_max_ns,wns_min_ns`.

`status` is `OK` (crossing found), `ABOVE_STOP` (still passes at `CLK_STOP`, so
the reported Fmax is a lower bound), or `FAIL_AT_START` (already fails at
`CLK_START`, so the sweep range must be raised).

## Measured results

Measured with the LibreLane 3.0.8 image (OpenSTA 2.7.0) and the nominal SPEF. The
20 ns point of every corner reproduces the released `runs/wokwi/final` metrics
exactly, which validates the flow.

| corner | setup slack @20 ns | hold slack @20 ns | period_fail | Fmax |
|--------|-------------------:|------------------:|------------:|-----:|
| nom_slow_1p08V_125C | +6.8725 ns | +0.6367 ns | 13.125 ns | **76.19 MHz** |
| nom_typ_1p20V_25C | +10.1574 ns | +0.2984 ns | 9.836 ns | 101.67 MHz |
| nom_fast_1p32V_m40C | +11.1362 ns | +0.1110 ns | 8.859 ns | 112.87 MHz |

Overall setup Fmax = **76.19 MHz**, limited by the slow corner. At every corner the
worst slack falls by exactly 1 ns per 1 ns of period reduction, confirming a
single fixed critical path. At the slow failing period the critical path had a
data arrival of 13.0308 ns against a required 13.0283 ns (-0.0025 ns); the full
path is in `test/sim_build/fmax/nom_slow_1p08V_125C/fmax_nom_slow_1p08V_125C.log`.

## Caveats

- Only the nominal SPEF is available (`spef/nom`), so the fast and slow corners
  pair corner liberty with nominal parasitics. This is the best available input
  and is conservative for the slow corner only if nominal RC bounds the slow RC.
- The 0.25 ns clock uncertainty is included, so the swept Fmax already carries
  the released closure derate.
- STA bounds logic timing only. Real-silicon operation is also limited by power
  grid IR drop (`docs/peak-power.md`), clock input slew and drive, and the Tiny
  Tapeout clock source, none of which this flow models.
- Hold is reported per point but is period-independent here; it bounds the clock
  duty-cycle/skew quality rather than the maximum period.
