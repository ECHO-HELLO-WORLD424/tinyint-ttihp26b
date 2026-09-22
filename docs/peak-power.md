# Post-layout cycle-peak power

This note reports the cycle-peak power of the routed IHP SG13G2 TinyInt design,
measured with the open-source peak flow in `synthesis/run_peak_power.sh`. It
complements the whole-trace average analysis in `power-analysis.md`, which only
reports one average per architecture mode.

## Method

1. `test/power_activity_tb.v` drives the same 8,192 signed MACs in every mode and
   writes a gate-level VCD (routed netlist + functional IHP standard cells).
2. `synthesis/peak_activity.py` bins every net transition into 20 ns clock
   windows, ranks windows by a capacitance-weighted switching proxy
   (`0.5 * C_spef * V^2 * flips`, V = 1.2 V), and emits a self-contained
   single-window VCD slice for the top `TOP_K` windows (default 32).
3. `synthesis/peak_power.tcl` reads the routed netlist, nominal SPEF, and one
   slice, then reports power with the same OpenSTA engine as the average flow.
4. `synthesis/analyze_peak.py` aggregates the per-mode average, peak, and
   peak/average ratio.

The bundled OpenSTA only implements `read_vcd [-scope]`, so the window is applied
by slicing the VCD rather than with a time-range option. The four modes use the
same stimulus and the same netlist; only the `CLEAR` mode payload differs.

## Results

Nominal corner (`nom_typ_1p20V_25C`), 50 MHz, 3,218 annotated pins in every
window, zero unannotated. All four modes peak in the same cycle (window 647,
12.94-12.96 us, the dense LFSR data segment).

| mode | average | cycle peak | peak/average | peak switching | average switching |
|------|--------:|-----------:|-------------:|---------------:|------------------:|
| conventional | 386.90 uW | 565.94 uW | 1.463 | 149.03 uW | 75.29 uW |
| dynamic-8    | 380.92 uW | 592.52 uW | 1.555 | 176.15 uW | 71.94 uW |
| dynamic-12   | 382.82 uW | 610.31 uW | 1.594 | 187.88 uW | 73.49 uW |
| dynamic-16   | 388.01 uW | 621.79 uW | 1.603 | 192.64 uW | 76.22 uW |

## Interpretation

The average-power ranking (dynamic-8 lowest, conventional mid) **does not carry
over to the peak**. On its worst cycle the conventional accumulator has the
lowest peak (565.94 uW); the dynamic modes are 4.7-9.9% higher, and the increase
grows with the active boundary. The entire difference is combinational switching:
the peak switching power rises from 149 uW (conventional) to 193 uW (dynamic-16),
consistent with the write-enable/event logic adding D-path capacitance that the
whole-trace average hides.

This is the peak analogue of the conclusion in `power-analysis.md`: the dynamic
accumulator reduces average combinational evaluation on typical cycles but does
not reduce, and slightly increases, the worst-cycle power.

## Validation

* Every candidate slice annotates all 3,218 pins with zero unannotated.
* Slicing is deterministic: generating the window-647 slice with `TOP_K` of 1,
  32, or 128 produces byte-identical slices and identical power.
* A `TOP_K = 128` sweep of dynamic-16 did not find a higher peak than the 32
  highest-activity windows (max 620.4 uW versus 621.8 uW at the same window),
  confirming that the proxy ranking captures the peak.

## Limitations

* The VCD is a zero-delay functional trace, so intra-cycle glitch power is not
  modeled; the true silicon peak is expected to be higher.
* Only the nominal PVT corner and one stimulus trace are measured.
* The result is a clock-granular cycle average, not an instantaneous or di/dt
  peak, and no power-grid IR-drop is modeled.
