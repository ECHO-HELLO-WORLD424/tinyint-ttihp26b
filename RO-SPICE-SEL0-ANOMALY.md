# The `ro_mat can_sel=0` "outlier" was a deck bug

Status: **resolved, 2026-09-09.** This note records what looked like an
unexplained circuit behaviour in the extracted RO transient (SPICE) dataset,
what it actually was, and how the dataset was corrected. Context:
[`docs/ro-spice-validation.md`](docs/ro-spice-validation.md).

## What was seen

In the first version of the 24-case SPICE sweep, one case family disagreed with
the broken-loop STA prediction in the *wrong* direction:

| Case | SPICE/STA frequency ratio |
| --- | --- |
| `ro_mat` `can_sel=0`, all three corners | **0.52 – 0.65** |
| every other case (21 of 24) | 1.01 – 1.17 |

`can_sel=0` is the shortest tap. SPICE has no wire RC while STA does, so SPICE
was expected to be *faster* than STA in every case, not 2× slower in one.
The case also showed 20–50 ps period jitter (others < 5 ps) and fewer settled
periods.

## What the waveform showed

Re-running the case with every ring node saved gave a consistent physical
picture — and pointed away from the circuit:

- The tap mux really did select the short branch: the mux output followed the
  loop node within ~100 ps, and the 132-inverter delay lines were dangling
  branches, exactly as the RTL intends for the shortest tap.
- The loop waveform was strongly asymmetric: high ~0.7 ns, low ~3.3 ns, period
  4.4 ns. The rising edge needed 873 ps to travel loop → mux → full adder →
  mux → full adder → tail → close; the falling edge needed ~3.4 ns.
- Per-stage fall delays were 4–7× the rise delays (mux 102 → 732 ps, full
  adder 338 → 1534 ps, and so on).
- An isolated `sg13g2_mux2_1` cell was symmetric (rise ~77 ps, fall ~105 ps)
  regardless of the unselected input's level, so the cell model was not the
  cause.

That asymmetry is what a ring does when its control pins are not actually
driven.

## Root cause

The deck generator wrote static control-pin sources as

```
Ven CTL_0__0913__X DC 1.2      ← wrong
```

instead of

```
Ven CTL_0__0913__X 0 DC 1.2   ← correct
```

ngspice parses the first form as a source between `CTL_0__0913__X` and a node
literally named `DC`, so the canary's `en`, `mask`, `rst_n` and mux `sel` pins
were **left floating**. Read back from the rawfile, they sat at 1.65–1.82 V
(above VDD) and 0.45–0.62 V (logic-ambiguous) instead of 1.2 V and 0 V. The
ring still oscillated, which is why the run looked plausible.

Minimal reproduction:

```
V1 a DC 1.2        R1 a 0 1k   →  v(a) = 0 V
V2 b 0 DC 1.2      R2 b 0 1k   →  v(b) = 1.2 V
```

## Fix and guard

- The generator now emits the ground node on every source
  (`tools/ro/run_ro_spice_case.py`).
- The sweep reads every static control pin back from the rawfile and records
  whether it settled within 50 mV of its intended value
  (`control_pins` column in `data/safe10/spice/spice_ro.csv`). All 24 cases
  report `ok`; the old decks would have failed this check loudly.

## Corrected result

With the pins actually driven, the 24-case sweep gives:

| Metric | Corrected | First version |
| --- | ---: | ---: |
| Mean SPICE/STA frequency ratio | **1.119** | 1.008 |
| Ratio standard deviation | **0.047** | 0.176 |
| Range | **1.041 – 1.222** | 0.521 – 1.170 |
| Outliers | **none** | 1 case family |
| `ro_mat can_sel=0`, typical corner | **458.8 MHz** (STA 400.0) | 226.0 MHz |

SPICE is now faster than STA in all 24 cases, which is the expected direction
for a netlist without wire RC. The gap shrinks as the inverter-dominated line
segment dominates the loop (correlation −0.91 with the line-segment share of
the STA loop delay), i.e. the largest disagreements are in the mux / gate /
full-adder cells, not in the inverter chains.

## Lesson

A ring oscillator simulation will happily oscillate with floating control
pins. Always read the static control state back from the result and assert it,
rather than assuming the deck did what it was written to do.
