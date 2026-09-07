# Area and accessible timing-boundary audit

Audit: 2026-09-06. Inspected checkout `96811e87dc11fdbb70785de9b84abc879ca3155d`.
Physical and timing evidence: archived CI run **33839023290**, RTL commit
`1e31757e50080b19fa7642b8b9cd6822f64b1d11`, LibreLane 3.0.5,
PDK revision `c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c`.
These are existing build results, not a new hardening run of the audit commit.

## Finding and recommendation

Both concerns deserve action, but they require different fixes. Active utilization
is genuinely high at **82.86%**. The stronger experimental problem is that a
failure boundary at **ambient temperature and nominal voltage has not been placed
inside the planned 1–50 MHz measurement range**. The slow-corner result does not
prove that heating the delivered die will make that boundary accessible.

For the fixed 1x1 design, first evaluate a **half-cycle DUT capture**, retaining
the physical delay banks, alongside area optimization of storage and control.
This avoids adding hundreds of inverters merely to slow the DUT. It changes the
measurement aperture and requires a new prediction/protocol version and complete
verification. It is a proposed design experiment, not an implemented fix.

If the original full-cycle experiment must remain unchanged, longer banks plus
a larger tile are the more straightforward fallback. A 1x2 tile changes the
project's explicit size specification and is therefore an alternative for the
owner to choose, not an assumed new baseline.

## 1. What the utilization actually measures

From `artifacts/run-33839023290/metrics.json`:

| Quantity | Value |
| --- | ---: |
| Core area | 28,941.5 µm² |
| Active standard-cell area | 23,980.9 µm² |
| Active utilization | 82.86% |
| Active cells | 1,747 |
| Filler cells | 863 |
| Sequential-cell area | 9,552.82 µm² (39.8% of active area) |
| Multi-input combinational-cell area | 8,319.02 µm² |
| Inverter area | 3,434.66 µm² |

Do not divide the all-instance area (28,941.5 µm², including fill) by core area
and interpret the resulting 100% as logic utilization. Likewise,
`PL_TARGET_DENSITY_PCT: 82` is a placement setting, not an area-saving mechanism.
Lowering that setting to 60 cannot fit the existing 23,981 µm² of active cells
in 17,365 µm² of available target area.

Tiny Tapeout's general FAQ discusses a 60% target to leave routing and added-cell
space. It is useful guidance, not evidence of an IHP26b foundry rejection rule
at precisely 60%. The archived build has zero DRC/LVS/antenna/hold violations,
but retains slow-corner setup violations. High utilization alone does not prove
the chip is unmanufacturable; it leaves little room for revisions and repair.
[Tiny Tapeout density guidance](https://tinytapeout.com/faq/#why-is-target-density-set-to-60-should-i-change-it-to-100-or-should-i-add-another-tile).

The required savings in the existing core are substantial:

| Final utilization objective | Active area to remove | Fraction of current active area |
| --- | ---: | ---: |
| 70% | 3,721.85 µm² | 15.52% |
| 65% | 5,168.93 µm² | 21.55% |
| 60% | 6,616.00 µm² | 27.59% |

An inventory of the preserved named netlist instances, using the pinned typical
Liberty cell areas, finds:

| Preserved structure | Cells | Area |
| --- | ---: | ---: |
| `u_dut.*` | 476 | 3,207.86 µm² |
| `u_ro_gen.*` | 58 | 364.69 µm² |
| `u_ro_mat.*` | 167 | 1,050.54 µm² |

These are **not full hierarchical block areas**: synthesis flattened counter
and control logic into anonymous instances. In particular, the RO rows exclude
their counters. The DUT alone contains 384 deliberately inserted bank inverters
(four banks, 48 pairs each). Removing these is counterproductive for accessible
timing failures. Even removing both preserved RO structures would save only
about 4.9 utilization percentage points, while destroying the comparison.

### Area optimization order

1. **Compare oracle implementations by synthesis.** The serial checker contains
   17 accumulator bits, step state, carry/done state, operand bit-selection
   muxes and enable/reset logic. A compact combinational reference adder might
   cost less than this sequential implementation. It must remain a separate,
   independently verified oracle and settle comfortably before comparison at
   every allowed operating point. An ordinary synthesized adder is a candidate,
   not a demonstrated area win or guaranteed fast implementation.
2. **Audit redundant state and wide enables/resets.** Check whether datapath
   registers that are initialized before use can avoid asynchronous reset;
   check the 16-bit window counter against its maximum 16,384-cycle window;
   examine frame/checker count sharing and counter increment/enable mapping.
   Two window bits alone will not deliver the required 6,616 µm² saving.
   Preserve boot behavior, freeze, first-error storage and configuration capture.
3. **Evaluate the byte readout mux and counter logic after mapping.** Their
   real costs must be measured, not inferred from short RTL. Keep the external
   byte protocol, 16-bit error/operation saturation and both 16-bit canary counts.
   Reverting canaries to 10 bits reintroduces the documented overflow problem.
4. **Re-harden the best candidate**, then lower placement density to what the
   actual mapped area supports. Use 60% as the desired endpoint; 65–70% are
   intermediate tradeoffs, not claimed compliance with a 60% recommendation.
   If savings fall short, explicitly choose architectural scope changes or a
   larger tile. Do not promise 60% from small register-width edits.

## 2. Temperature is being confused with a PVT corner

Existing case-analyzed STA for seg3333/worst gives:

| Library corner | DUT data delay | Predicted full-cycle boundary |
| --- | ---: | ---: |
| Fast process, 1.32 V, −40 °C | 10.84 ns | 89.526 MHz |
| Typical process, 1.20 V, 25 °C | 15.88 ns | 61.463 MHz |
| Slow process, 1.08 V, 125 °C | 24.96 ns | 39.339 MHz |

The boundary includes setup/clock/uncertainty terms, so it is not simply
1000 divided by the data-delay column. The IOPATH-only SDF sweep corroborates
the accessibility problem: typical fails at 14 ns and passes at 16 ns, whereas
slow fails at 22 ns and passes at 24 ns. It omits interconnect and timing checks,
so it is not complete physical failure modeling.

**Process is not a knob on the hot plate.** Heating a typical die to 125 °C
does not turn it into slow-process silicon; holding voltage at 1.20 V also does
not reproduce the 1.08 V corner. The three supplied corner points vary process,
voltage and temperature together. They cannot establish a temperature threshold
or a reliable 25→85 °C interpolation for a particular die.

The existing post-silicon protocol actually specifies ambient plus about 85 °C
if available, not a mandatory 125 °C test. Its fallback matching an achievable
temperature to the slow corner therefore does not establish accessibility.
Such points must be labeled as model mismatch, not predictions at measured PVT.
Obtain fixed-process V/T characterization or extracted transient simulations
at the actual planned points before making that claim.

125 °C is not established here as either a destruction threshold or a safe
board temperature. IHP describes temperature-dependent model coverage extending
to 125 °C; that is not a packaged Tiny Tapeout assembly operating guarantee.
Package, power dissipation, junction-to-sensor gradient and board components
must be considered separately. Do not heat the whole development kit to 125 °C
to rescue the experiment. Even an 85 °C test requires a suitable fixture and
verified component limits; use ambient for initial observability acceptance.
[IHP model-temperature context](https://www.ihp-microelectronics.com/fileadmin/pdf/reports/annualreport_2022.pdf).

The 50 MHz limit should remain the design's conservative measurement envelope.
The Tiny Tapeout FAQ's “at least 50MHz” statement is explicitly in its TT04–TT10
section; it does not certify an IHP26b kit ceiling or approve a faster external
clock. Verify the actual delivered clock path before considering overclocking.
[Tiny Tapeout clock context](https://tinytapeout.com/faq/#what-is-the-top-clock-speed).

## 3. Ways to bring the boundary into range

### Preferred candidate: half-cycle capture

Keep operand launch on the rising edge at the frame boundary; capture the DUT
once on the following falling edge; retain rising-edge checker/control logic.
The frame can still contain 19 clocks. The data aperture becomes the clock's
high time, approximately T/2, instead of one whole period.

With unchanged delays and ideal 50% duty, halving the existing STA frequencies
gives first-order estimates of **30.73 MHz typical**, **44.76 MHz fast**, and
**19.67 MHz slow** at maximum taps. These are feasibility estimates, not new
STA results. They suggest ambient operation without extra delay area. The
fast estimate has limited margin below 50 MHz; it is not a room-temperature
fast-die guarantee.

Do not merely change `posedge` to `negedge` and declare completion. Required work:

- Re-evaluate capture enable on the falling edge after operand launch; retain
  exactly one capture and a held sample until compare. Preserve FORCE_ERR.
- Define freeze/resume during the launch-to-capture interval so an interrupted
  operation cannot be counted as a valid late capture.
- Model rising-to-falling paths, actual input high/low times, pulse-width limits,
  duty distortion, opposite-edge CTS skew, falling-edge flip-flop setup and
  result-to-checker comparison timing. Do not use combinational clock gating.
- Characterize duty cycle at the delivered clock path. Frequency alone no longer
  defines the timing aperture. Store high time and uncertainty in the raw schema.
- Run RTL and GL regressions, fresh hardening/structural checks, case-analyzed
  STA and sensitizing SDF or extracted simulations. Recompute canary counts at
  the lower operating frequencies and recheck overflow even at the shortest window.
- Version the research protocol and calibration model to express boundary vs
  measured aperture. A nominal 50% clock assumption cannot be silently fitted
  away as DUT prediction error.

### Full-cycle fallback: longer delay banks

The typical full-cycle threshold is about 16.27 ns. A 40 MHz boundary requires
about 25 ns, or **8.73 ns more delay**. From the existing uniform tap ladder,
each additional tap across all banks adds about 3.52 ns for 128 inverters.
Linear extrapolation therefore suggests roughly **318 additional inverters**
for 40 MHz typical, about **1,731 µm²** or **6 core-utilization percentage points**.
This is only a sizing estimate; routing, slew and load require new extraction.
It would take present utilization toward 89%, before extra repair/CTS effects.
This approach conflicts directly with the area goal unless other logic shrinks
substantially or the tile grows. Fast-silicon observability needs still more margin.

### Conditional alternatives

- **Lower core voltage:** characterize at ambient with a verified adjustable
  core rail. Shared supply topology, IO voltage domains, checker/control margins
  and RO counter operation must remain valid. The existing three-corner dataset
  does not predict the required undervoltage. Do not substitute a 1.5 V library
  for the design's 1.2 V operating models.
- **External faster clock:** potentially useful only after board/pad/mux clock
  delivery is verified. It is not a solution that satisfies the present ≤50 MHz
  requirement and requires a new safe envelope for the checker/control.
- **Accept censored data:** statistically honest when no error occurs at 50 MHz,
  but it cannot provide the intended measured boundary or boundary calibration.

## 4. Revised acceptance gates

The existing archive remains a useful physical baseline. Its fully checked
readiness checklist should not be read as proof of a reachable laboratory knee.
Before freezing a revised build, require:

- [ ] A boundary with margin inside 1–50 MHz at **1.20 V and ambient**, with
      process/model uncertainty assessed; target roughly 25–40 MHz typical.
- [ ] A clean control/oracle envelope throughout the intended failure sweep.
- [ ] Final utilization at the chosen area objective, measured after routing.
- [ ] Physical signoff and prediction artifacts from the exact revised RTL build.
- [ ] Versioned protocol for the actual aperture, board and reachable V/T grid.

## Reproduction and scope

Inside the repository devcontainer:

```sh
python3 tools/audit_feasibility.py > data/feasibility_audit.json
```

The script inventories all 2,610 netlist instances, verifies every cell has a
pinned Liberty area, checks total area against the physical report within 0.1%,
checks timing-table source identity, and records SHA-256 hashes of its inputs.
Liberty total area is 28,939.3776 µm² versus rounded physical area 28,941.5 µm²;
use the physical metrics for utilization and Liberty only for the inventory.

This audit changes documentation and adds reproducible report tooling. It does
not change RTL, constraints, the frozen prediction CSVs, or the submitted build.
No new synthesis, hardening, RTL/GL regression or transistor transient simulation
was run. Candidate savings and half-cycle boundaries remain unvalidated until
the implementation and verification gates above are completed.
