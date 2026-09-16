# Post-silicon readiness audit (2026-09-16)

> **Status of this document.** Written during the final ttihp26b submission review, on
> top of branch tip `3cd953d` (`proposal-canary`) with the audited CI run
> `34853386333` (gds / precheck / gl_test / viewer all `success`). It records every
> problem found that could compromise the post-silicon measurement, together with the
> evidence, and states which items were fixed in-tree and which remain open.
>
> **Finding F1 was fixed in this pass** and changes `src/`, so the archived build
> evidence is now stale: a fresh hardening run and a regenerated
> `artifacts/run-*/manifest.json` are required before submission. See
> [Required follow-ups](#required-follow-ups).

## Scope and method

Static review of RTL, constraints, floorplan configuration, tests and user
documentation; directed simulation of protocols the stock testbench cannot observe;
cross-checks against the SPICE RO dataset, the case-analyzed experiment STA, and the
canonical CI artifacts of the submitted commit.

Commands and artifacts used:

| Evidence | Where |
| --- | --- |
| RTL cocotb regression (13 tests, then 14 with the new test) | `test/`, dev container, iverilog 12.0 / cocotb 2.0.1 |
| CI artifacts of tip `3cd953d`, run `34853386333` | `runs/audit-ci/` (gitignored) |
| Bidirectional-pad testbench, committed as `test/tb_pad_contention.v` | Run from the repo root; also wired into the `test` CI workflow |
| SPICE RO dataset | `data/safe10/spice/ro_spice_vs_sta.csv` |
| Case-analyzed experiment STA | `data/safe10/experiment_sta.csv`, `data/safe10/predict/` |
| Post-route per-corner timing / DRV / DRC / LVS | `runs/audit-ci/GDS_logs/runs/wokwi/` |

**Not covered:** the FPGA harness was not run (board disconnected). No local LibreLane
hardening was performed (the dev container was started without its DinD sidecar); all
physical-design evidence comes from the CI artifacts of the submitted commit.

## Findings summary

| # | Severity | Finding | Status |
| --- | --- | --- | --- |
| F1 | **Blocking** | `uio_oe` asserted one clock before the configuration-commit edge → guaranteed host/chip pad contention and a corrupted `cfg[15:8]` | **Fixed** (RTL + docs + test) |
| F2 | High | `FREEZE` (`ui_in[7]`) has no synchronizer and the host contract does not require clock-aligned changes → possible spurious error counts | **Settled** (documented host contract; no RTL change) |
| F3 | Medium | Canary counters silently alias above 65535 for most window/frequency combinations; no overflow flag | Open |
| F4 | Medium | The canary window is one-shot and cannot be re-armed without reset; the datasheet calls it "continuous" | Open |
| F5 | Medium | RO ripple counters are excluded from all timing signoff and are never exercised at speed | Open |
| F6 | Medium | `ops_cnt` counts launches, not comparisons; the datasheet byte map omits the −1 | Open (docs) |
| F7 | Medium | The archived final-build manifest describes a different commit than the submitted tree | **Resolved** (run `35034979531` archived) |
| F8 | Low | `MAX_FANOUT_CONSTRAINTS` is not a LibreLane variable and is silently ignored | Open |
| F9 | Low | Stale documentation references (`chk_start`; `PRE_SILICON_ACTION_PLAN.md` missing) | Open |
| F10 | Medium | Environment: the aperture is the clock HIGH time, and the demo-board clock's HIGH time is an integer-division artefact that must be measured, not assumed 50 % | Open (campaign) |
| F11 | Medium | Environment: voltage sweep and uio drive/release need a fixture beyond the standard demo board | Open (campaign) |
| F12 | Low | RF on `uio` during the RO window; power/IR numbers exclude the ROs | Open (campaign) |

---

## F1 — (blocking) configuration capture corrupted by `uio_oe` off-by-one — FIXED

**Symptom.** The chip begins driving all eight `uio` pads one clock cycle *before* the
edge at which it latches the configuration word, while the host is still required to be
driving that same word. `cfg[15:8]` (pattern select, canary select, window select,
`FORCE_CAN`, `FORCE_ERR`) is therefore sampled from a contended bus.

**Root cause.** `src/tt_um_echoworld424_tpv.v` asserted the output enable from
`boot[1]`, which is high for `boot == 2` *and* `boot == 3`:

```verilog
assign uio_oe = {8{boot[1]}};   /* boot[1] set at boot==2, one edge too early */
```

`cfg` is captured at the *next* edge (`else if (boot == 2'd2) cfg <= cfg_word;`). The
host contract is explicit — `docs/post-silicon-protocol.md`: *"Hold pins stable through
three complete rising edges after release, then release host uio drivers"* — so the
double-drive is mandated by the documented protocol, not an operator error.

**Impact.** `pat_sel`, `force_can` and `force_err` are **not echoed in any status byte**
(byte 8 echoes `cfg[7:0]`, byte 9 echoes `can_sel`/`win_sel` only), so a corrupted upper
byte is undetectable by read-back: the campaign would silently measure the wrong
pattern. A pad fight also draws crowbar current through the chip's IO and the RP2040
GPIO for a full clock period on every reset, repeated for every point of the sweep.
There is no clean host workaround: releasing `uio` early makes the chip drive its own
`ro_byte` (= `0x00`, RO still disabled) into `cfg[15:8]`, deterministically forcing
PRBS/`can_sel=0` instead of the required worst-case anchor.

**Why existing verification missed it.** `test/tb.v` wires `uio_in` (a testbench `reg`)
and `uio_out` (a DUT `wire`) as separate nets, so the pad is never modelled and
contention is unobservable. The FPGA harness `fpga/tt_fpga_pico2ice.v` *already
documented the defect and worked around it* by latching `uio` while `rst_n` is low and
holding it for the DUT, which is why the FPGA flow never surfaced it either.

**Evidence.** Icarus testbench with the host driver and the chip driver on one net:

```verilog
assign uio_pad = host_oe ? host_drv : 8'bz;
assign uio_pad = uio_oe  ? uio_out  : 8'bz;
assign uio_in  = uio_pad;
/* host drives CFG = 0x09E7 and holds it through three rising edges */
```

```
=== before the fix (uio_oe = boot[1]) ===
  rising edge 1: uio_oe=00000000 pad=00001001 cfg=0000
  rising edge 2: uio_oe=11111111 pad=xxxxxxxx cfg=0000 <<< HOST/CHIP CONTENTION
  rising edge 3: uio_oe=11111111 pad=xxxxxxxx cfg=xxe7 <<< HOST/CHIP CONTENTION
final cfg = xxe7 (host wanted 09e7) -> CORRUPTED

=== after the fix (uio_oe = boot_done) ===
  rising edge 3: uio_oe=00000000 pad=00001001 cfg=09e7
final cfg = 09e7 (host wanted 09e7) -> LATCHED OK
```

**Fix applied.** The output enable is now driven by a `boot_done` flag that is set only
once the boot counter has reached its final value, giving the host a full clock period
of dead time after the commit edge:

```verilog
reg boot_done;
always @(posedge clk or negedge rst_n) begin
  if (!rst_n) boot_done <= 1'b0;
  else if (boot == 2'd3) boot_done <= 1'b1;
end
assign uio_oe = {8{boot_done}};
```

Timing contract now: edges 1–3 after reset release = host drives `uio` (edge 3 is the
commit edge; the chip must not and does not drive); the chip takes the bus on edge 4;
the `uio` value after the commit edge is a don't-care because `cfg_word` is only
consumed by the capture. Costs one flip-flop and one clock of latency on a readout path
that the host already delays by freeze + settling cycles.

**Verification of the fix.**

- Pad-level testbench (host driver and chip driver on one net), run against both
  revisions:

  | Revision | Contention during the host window | Committed `cfg` | Verdict |
  | --- | --- | --- | --- |
  | pre-fix `boot[1]` | rising edges 2 and 3 | `xxe7` | FAIL (3 violations) |
  | fixed `boot_done` | none | `09e7` | PASS (0 violations) |

  `uio_oe` is `0x00` at edges 1–3 and `0xFF` after the dead cycle in the fixed
  revision.
- `test/test.py::test_uio_oe_handoff` asserts `uio_oe == 0` at each of the first three
  rising edges after reset release, `0xFF` after the dead cycle, and re-checks the
  configuration echo. **Negative control:** against the pre-fix RTL it fails at rising
  edge 2 with `chip drives uio at rising edge 2 after reset release; the host still
  holds the configuration word`, so the regression is real.
- Full RTL cocotb regression: **14/14 pass** (13 baseline + the new test).
- Reset-timing sweep over the fixed RTL (one-off audit script): 28 combinations of
  reset pulse length (1, 2, 4, 7 clocks) × reset-release phase (0, 1, 5, 9.5, 10, 10.5,
  15 ns after a falling edge on a 20 ns period — including release exactly on a rising
  edge) → **0 violations**: no chip drive during the three-edge host window, the chip
  owns `uio` after the dead cycle, and `cfg` latches the driven word in every case.
- Functional GL against the pre-fix archived netlist: **9 pass / 1 fail / 4 skip** — the
  failure is `test_uio_oe_handoff`, which both confirms the defect is present in that
  netlist and gives the host tree a reliable stale-netlist signal.
- Emulator regression fixture (`tools/chip_emulate.py selftest`, a separate harness that
  drives the DUT through its own testbench): all 10 checks pass, including
  `uio drives after boot: uio_oe=0xFF` and `config echo: cfg_echo=0xFF segs=3333`.
- Verible lint reports only the three pre-existing style findings in the file
  (trailing space at line 26, `FRAME_LAST` storage type, `always @*`); the added code
  introduces none, and `verible-verilog-format` reproduces only the intended change.

**Permanent protection added.** The pad model is committed as
`test/tb_pad_contention.v` (self-checking, `$fatal` on contention, standalone — it is
not part of the cocotb build because `test/Makefile` lists `tb.v` explicitly) and is
run as a new `Check the uio pad hand-off` step in `.github/workflows/test.yaml`.
`test_uio_oe_handoff` covers the property in the cocotb suite; the pad instrument
covers the actual failure mode. The pre-fix RTL fails both.

**Consequential edits.** `docs/info.md` (step 1), `docs/post-silicon-protocol.md`
(step 2), `AGENTS.md` (protocol subsection, current-blocking-work entry and repository
map), `test/README.md` (GL netlist provenance and the new instrument), the top-level
file header, and the now-obsolete workaround note in `fpga/tt_fpga_pico2ice.v`.

---

## F2 — `FREEZE` is not synchronized and the host contract does not require edge alignment — SETTLED

`src/tt_um_echoworld424_tpv.v`: `wire freeze = ui_in[7]; wire update_en = ~freeze;`
drives the clock-enable of `frame_cnt`, `win_cnt`, `err_cnt`, `ops_cnt`, `started` and
(via `load`) `capture_pending`, and gates the RO loop. `FREEZE` is driven from the
host's own time base; nothing in `docs/` requires it to change away from a clock edge,
and the SDC's `set_input_delay 4.000` for `ui_in[7]` is a *synchronous* assumption the
host is not obliged to satisfy.

If `update_en` resolves differently per flop — or if `capture_pending` misses the frame
boundary — the frame/ops/err relationship can break until reset, or the *previous*
`result_reg` contents are compared against the *new* operands and a **fabricated error
is counted**, which is the primary measured quantity. A freeze is issued at every
measurement point, so the exposure is repeated.

Cheapest adequate fix: a two-flop synchronizer for `freeze` (with `ro_en` taken from
the synchronized version), or an explicit documented requirement to change `FREEZE`
while the clock is low and at least ~20 ns before the next rising edge. If neither is
done, treat "error count non-zero on a config that should be error-free" as a
freeze-transition artefact before recording it.

### Decision (2026-09-16): documented host contract, no synchronizer

The paragraphs above describe the state at audit time. The second option was taken, and
the contract is now normative in `docs/post-silicon-protocol.md` (§ "FREEZE interface
contract (`ui[7]`)") and stated for users in `docs/info.md`:

- The host must transition `FREEZE` — assert **and** release — during the clock HIGH
  phase, which guarantees between half and one full period of settling ahead of the
  sampling edge (50–100 ns at 10 MHz, 10–20 ns at 50 MHz). A host that can only act in
  the LOW phase must still land the transition at least 20 ns (10 MHz) or 10 ns
  (50 MHz) before the next rising edge, proven on a scope. Both floors exceed the 4 ns
  input-path budget `src/pnr.sdc` already places on `ui_in[7]` with
  `set_input_delay 4.0000`. The HIGH-phase rule is stated rather than a single
  nanosecond figure because it is frequency-independent: one rule covers the whole
  10–50 MHz sweep, and a flat figure cannot (20 ns is unreachable inside a 10 ns LOW
  phase at 50 MHz).
- `FREEZE` must be generated in the chip's clock domain. An OS-scheduled software GPIO
  write is explicitly disqualified, because it cannot bound its own jitter to a
  sub-100 ns window.
- A per-session scope check of `clk` against `ui[7]`, recorded with `host_fw` in the run
  notes, discharges the obligation for that session.
- Escalation rule: a nonzero error count on a configuration that the model and the
  `alt`/`hold` controls say is error-free is a suspected freeze-transition artefact
  until the scope check is on record; an operating point whose host cannot satisfy the
  rule is excluded with a reason code rather than reported as data.

Rationale for **not** synchronizing in RTL: a two-flop synchronizer would add two cycles
of freeze latency, make the operation count at the freeze boundary timing-dependent by
one (interacting with F6's `ops_cnt` definition), and change when `ro_en` stops the ring
— perturbing a quantity the experiment measures — while `src/pnr.sdc` already assumes a
synchronous input. The trade was moved to the host, where it is enforceable and
re-checkable every session, rather than into RTL that cannot be changed after tapeout.

Consequences recorded deliberately: this is a **host-side obligation, not a hardware
guarantee**, so the chip in isolation is not certified against the F2 failure mode, and
a host that ignores the contract reproduces the exposure exactly. The obligation is also
not discharged by the reference harness, which routes host GPIO `ui_cfg` straight to
`ui[7]` in the run phase (`fpga/tt_fpga_pico2ice.v:68`) and synchronizes nothing.

Consistency with the regression: `test/test.py::test_freeze_resume_every_phase`
transitions FREEZE at mid-HIGH phase (exactly half a period before the next rising edge)
and the `freeze()` helper transitions at mid-LOW phase. Both exercise **functional**
freeze semantics in a zero-delay simulator, which does not model setup/hold and so
cannot validate the host timing contract in either direction — the same caveat is now
recorded in `tools/emulator/README.md` for the host driver, whose pin writes land 1 ps
before a rising edge. Nothing in the regression contradicts the contract; the contract's
evidence is the host-side scope check. No RTL was changed, so this decision required no
re-hardening run and no re-run of the prediction packages; what remains is host-side.

## F3 — canary counters silently alias, with no overflow flag

Edge count `= f_ro · N_win / f_clk`, stored in a 16-bit counter that wraps (the wrap is
deliberate and documented in `docs/data-dictionary.md`, and asserted by
`test_ro_ripple_counter_wrap`). From the SPICE dataset, at the nominal corner
(1.20 V / 25 °C) with the *fastest* canary selection and a 10 MHz clock:

| Canary | `win=0` (2^8) | `win=1` (2^10) | `win=2` (2^12) | `win=3` (2^14) |
| --- | ---: | ---: | ---: | ---: |
| `ro_gen`, `can_sel=0` | 21 130 ✓ | **84 523 WRAP** | **338 094 WRAP** | **1 352 376 WRAP** |
| `ro_gen`, `can_sel=3` (protocol default) | 7 425 ✓ | 29 700 ✓ | 118 803 WRAP | 475 213 WRAP |

A wrapped 84 523 is read as 18 987, i.e. 185 MHz instead of 825 MHz — a 4.5× error in
the predictor variable — and a count that wraps to exactly zero is additionally
reported as `*_ro_dead`. `win_sel=3` overflows for every canary/selection pair at
10 MHz, and at 50 MHz for all but the matched canary at `can_sel` 2 and 3 (47 249 and
35 554 edges at the typical corner). The docs warn about this and
`docs/post-silicon-protocol.md` says to "check telemetry for overflow risk", but the
hardware gives the host nothing to check against, so the check is circular.

Mitigation without an RTL change: restrict the campaign to `can_sel=3`, `win_sel=0`
(which the protocol already selects) and reject any telemetry whose predicted count
would exceed 65535. A future revision should add an overflow flag or clamp the window
encoding.

## F4 — the canary window is one-shot

`win_done` is cleared only by `rst_n`, so `ro_en = update_en & ~win_done & (boot == 3)`
never re-arms. After 2^8…2^14 clocks the ring oscillators stop for the remainder of the
run. Consequences: (a) the canary sample is taken in the first 26 µs–1.6 ms after reset
while error statistics accumulate over a run that can be seconds long, so the two are
not measured under identical thermal/IR conditions; (b) the datasheet's "providing
continuous delay telemetry" (`docs/info.md`) overstates the behaviour — it is a
single-shot sample per reset. One sample per configuration is workable because the
host resets for each point, but the wording should be corrected and the timing
(RO window at the start of the run) recorded in the analysis.

## F5 — RO counters are outside all timing signoff

`src/pnr.sdc` disables timing for the entire `*u_ro_gen*` / `*u_ro_mat*` hierarchies,
so the ripple-counter flops have no checked CK→Q, setup/hold or toggle-rate limit.
`cnt[0]` toggles at `f_osc/2`, up to ≈625 MHz at the fast corner. The extracted SPICE
validation proves the *loop* oscillates with the counter attached (the probed node is
the counter clock pin), but it does not prove the counter counts correctly at that
rate; the GL test strips the loops and asserts the counters stay at zero, and the RTL
counting test runs only with `TPV_GDELAY=1` (≈10 MHz equivalent) at `can_sel=3`. So
"counts correctly at speed" and "counts correctly at `can_sel` 0–2" are both currently
unverified. First-silicon check: `can_sel=0`, `win_sel=0`, `FORCE_CAN=0` → expect a
plausible, non-zero, ratio-consistent `gen_cnt`/`mat_cnt`.

**Correction and closure (2026-09-16).** The second sentence above overstates what the
f_osc decks do. The extracted ring subcircuit contains the counter's first flop as a
load, but not its toggle inverter or the other 15 ripple stages, so the flop's `D` pin
and the shared reset tree became deck control pins — and every revision-2 deck drove
both to 0 V, i.e. **the counter was held in reset**, not merely static. A separate
procedure was therefore required rather than a re-reading of the existing one:
`tools/ro/extract_ro_loop.py --counter`, `tools/ro/run_ro_count_case.py`,
`tools/ro/analyse_ro_count.py`; dataset `data/safe10/count/`; record
`docs/ro-counter-spice-validation.md`. Building it surfaced the trap this finding
implies: the counter's toggle feedback must be inside the subcircuit *and* its reset
tree must be walked back to `rst_n`; otherwise the deck drives a buffer output against
the tree and silently reproduces the defect. **Status: closed for the RTL/netlist-level
counter** (all 12 corner × canary × `can_sel` cases count the ring's edges, with the
ring frequency unchanged by the running counter). F3 (counter aliasing over a full
2^8…2^14 window) remains open. First-silicon check unchanged: `can_sel=0`,
`win_sel=0`, `FORCE_CAN=0` → expect a plausible, non-zero, ratio-consistent
`gen_cnt`/`mat_cnt`.

## F6 — `ops_cnt` counts launches, not comparisons, and the datasheet does not say so

`ops_cnt` increments on every frame boundary including the pipeline-fill one that
`started` suppresses for `err_cnt`, so completed comparisons `= max(ops_cnt − 1, 0)`.
This is asserted by `test_force_err_accounting` (ops = 100, `err_cnt` = 99) and is
documented in `docs/post-silicon-protocol.md` and `docs/data-dictionary.md`
(`n_compared`), but **not** in the user-facing `docs/info.md` byte map, which says only
"6-7 = op count (saturating)". A host written from the datasheet alone biases every
error rate low. Add the −1 to the datasheet byte map.

## F7 — the archived final-build manifest does not describe the submitted tree

`artifacts/run-34158224984/manifest.json` records
`ci_commit = b9f03f798978840c8bdc2bb574877408e0f33f4c` and
`submission/src/tt_um_echoworld424_tpv.v` sha256 `2404067…` (9836 bytes); the branch
tip is `3cd953d` with sha256 `d3e749f…` (10183 bytes). The delta is whitespace plus one
comment block (`git diff -w b9f03f7..HEAD -- src/` is otherwise empty) and CI *has*
been re-run green on the tip, so the GDS itself is very likely unchanged — but the
evidence chain the repository's own definition of done requires (hashes of the files
actually analysed) is broken. `docs/pre-silicon-v2-blog.md` was also uncommitted at the
time of this audit.

**Resolved (2026-09-16).** The fix was committed and pushed; CI run `35034979531` on
commit `0a7cd5e` is archived as `artifacts/run-35034979531/` with a regenerated
`manifest.json`/`MANIFEST.md` that hashes the staged CI artifacts of that exact
commit, plus precheck and functional-GL evidence.

## F8 — `MAX_FANOUT_CONSTRAINTS` is silently ignored

`src/config.json` sets `"MAX_FANOUT_CONSTRAINTS": 400` and its comment claims this is
needed "to place and legalize". LibreLane has only `MAX_FANOUT_CONSTRAINT` (singular):
the installed LibreLane 3.0.0.dev44 contains no plural symbol, and the resolved
configuration of run `34853386333` carries `MAX_FANOUT_CONSTRAINT = 10` (the default)
with no plural key at all. `src/pnr.sdc` separately sets `set_max_fanout 100`. Three
inconsistent numbers, and the one meant to take effect never does.

Consequence in signoff: `design__max_fanout_violation__count = 1` —
`clkbuf_0_clk/X`, fanout 16 against a limit of 8. Benign in practice (a clock buffer
driving leaf flops), but the check is not clean and AGENTS.md requires it to be
inspected. Either correct the key or delete the stale claim and document the effective
constraint.

## F9 — stale documentation references

- `docs/data-dictionary.md` describes the DUT capture as "one-shot `result_reg`
  capture at frame cycle 0 (`chk_start`)" — `chk_start` is a v1/full-cycle signal that
  no longer exists; the half-cycle design uses `capture_pending`.
- `AGENTS.md` requires reading `PRE_SILICON_ACTION_PLAN.md` and points at its
  definition-of-complete checklist, but **that file is not in the working tree** (it
  exists only in git history). Either restore it or remove the references.
- `docs/info.md` "continuous delay telemetry" — see F4.

## F10 — environment: the aperture is the clock HIGH time, so the clock source is an instrument

The design measures across the clock HIGH phase, not the full period (`docs/info.md`:
"10 ns at 50 MHz/50% duty, not the full 20 ns period"). The Tiny Tapeout demo board
generates `clk` from the RP2040 via PWM (`tt.clock_project_PWM(hz)` in
[ttcontrol.py](https://github.com/TinyTapeout/tt-commander-app/blob/main/src/ttcontrol/ttcontrol.py)),
i.e. by integer division of the system clock; the
[TT clock specification](https://tinytapeout.com/specs/clock/) shows an example
"25.179 MHz clock waveform generated by the RP2040". The HIGH time is therefore
quantized to RP2040 system-clock cycles, and a clean 50 % duty is not guaranteed at
arbitrary sweep frequencies. At the typical anchor, +1 ns of HIGH time moves the
predicted boundary from 31.0 MHz to ≈29.2 MHz (≈6 %).

The protocol already requires recording frequency, HIGH time and duty and reporting
brackets in HIGH time, which is the right mitigation; the remaining gaps are (a) an
external low-jitter clock is currently only *recommended* and should be mandatory for
the fine sweep, (b) the HIGH time must be measured at the chip's clock pin, not only at
the board source — TT's general clock specification notes up to 10 ns of pad-to-project
insertion delay, without giving an IHP-specific figure, so the board-to-tile distortion
must be characterised rather than assumed negligible — and (c) with a 2.5-system-clock
period at 50 MHz the divider jitters cycle-to-cycle, so a single HIGH-time number does
not describe the aperture distribution; record min/typ/max. The absolute claim "the
demo board cannot hold 50 % duty at 50 MHz" is *not* established here: the ttboard
firmware may re-tune the RP2040 clock to make the divider integral. What is established
is that the HIGH time is an integer-division artefact and must be measured, not
assumed.

## F11 — environment: fixture requirements beyond the standard demo board

The voltage sweep needs an adjustable core supply (verify board power topology first,
as the protocol already says), and the host must be able to **drive and then release**
`uio` with cycle-level control of `rst_n` and the configuration window. A plain
MicroPython REPL cannot meet the release timing; the documented contract implicitly
assumes a PIO/firmware or FPGA host (the `fpga/` harness is the intended model).
Temperature remains optional and correctly de-scoped. Fail-safe: a die faster than the
fast library corner is not fatal — the boundary can be pulled into the 10–50 MHz range
with the `3333` taps and/or a lower supply — but it will be right-censored at 50 MHz
otherwise, so record censoring rather than forcing an anchor.

## F12 — RF on `uio` during the RO window; optimistic power/IR numbers

While the canary window is active, `ro_ptr` cycles and `uio_out` carries raw ripple
counter bytes, including `cnt[0]` at up to ≈600 MHz, onto the pads. That is an
EMI/crosstalk source during the measurement window, and the pad cannot follow at that
rate under a real board load (STA models 6 fF; LibreLane `OUTPUT_CAP_LOAD = 6`). Read
only after the window has stopped, as the protocol already requires, and expect the
canary bytes to be meaningless mid-window. Relatedly,
`design_powergrid__drop__worst = 0.385 mV` and `power__total = 0.237 mW` exclude the RO
switching (their timing is disabled, so they carry no activity), and the ROs are the
largest dynamic consumers. Not a blocker at 0.39 mV, but do not quote those numbers as
worst case for the canary window.

---

## Verified clean on the pre-fix submitted commit (`3cd953d`)

> These numbers describe the state at audit time, before F1 was fixed. They are
> reproduced exactly by the post-fix CI build — see
> [Canonical CI build and cross-verification](#canonical-ci-build-and-cross-verification-2026-09-16).

- **RTL regression:** 13/13 cocotb pass at tip `3cd953d` (re-run locally in the dev
  container on the current sources; 14/14 after adding `test_uio_oe_handoff`).
- **Functional GL:** 9 pass / 4 intentional skips (CI run `34853386333`).
- **Post-route STA at 100 ns:** setup WS **+24.59 ns**, hold WS **+0.134 ns**, zero
  setup/hold violations at all three corners. The intentional half-cycle DUT path is
  the design-global worst path at *every* corner, so a 10–50 MHz sweep pushes only the
  intended path into failure; no control, checker or readout path is close to the
  50 MHz budget.
- **Physical:** Magic DRC 0, LVS 0, antenna 0, illegal-overlap 0, power-grid 0, routed
  DRC 0, one *non-critical* disconnected pin (the intentionally unused `ena`),
  utilisation 73.7 %, 152 sequential cells.
- **Structural preservation:** the submitted netlist contains 705 `sg13g2_inv_1`,
  55 `sg13g2_mux2_1`, 53 `sg13g2_xor2_1` — consistent with the 384 DUT bank inverters,
  the 192 RO-line inverters, the tails and the tap muxes. Both RO loops and all four
  delay banks survive synthesis.
- **Experiment margin:** the primary anchor (seg3333/worst) is predicted inside the
  10–50 MHz sweep at all three library corners — 31.0 MHz (typ 1.20 V/25 °C),
  19.9 MHz (slow 1.08 V/125 °C), 45.1 MHz (fast 1.32 V/−40 °C).

## Local re-hardening and full-flow verification of the F1 fix (2026-09-16)

The whole submission flow was re-run locally on the fixed RTL, in the repository
devcontainer, following the same steps as `.github/workflows/gds.yaml`:

```
tt/tt_tool.py --ihp --create-user-config        # byte-identical user_config.json
tt/tt_tool.py --ihp --harden                    # LibreLane, --dockerized
tt/tt_tool.py --ihp --print-stats / --print-cell-category
tt/tt_tool.py --ihp --create-tt-submission
tt/precheck/precheck.py --gds <tt_submission>/…gds --tech ihp-sg13g2
cd test && make GATES=yes                       # netlist from the new run
```

Build identity: LibreLane `3.0.5` (`ghcr.io/librelane/librelane:3.0.5`), PDK
`ihp-sg13g2` at CIEL revision `c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c` — the same
PDK revision as the audited CI run — on a dirty tree at commit
`3cd953df6d7d6f224ff9ff3bbb4e2cb9fde258b3` (the F1 fix is not yet committed).

| Artifact | SHA-256 |
| --- | --- |
| `runs/wokwi/final/gds/tt_um_echoworld424_tpv.gds` | `b4de5533b2ef427235c76b69474b39272cc9592011a46fdb8a8601e3caf0a60d` |
| `runs/wokwi/final/nl/tt_um_echoworld424_tpv.nl.v` | `e889762e1fffa169edb4342cc126660965f239c851552ebfc2e57f8d7e11c177` |
| `tt_submission/tt_um_echoworld424_tpv.oas` | `74c31c6e732313ee3a86195e89f5e5416e26f3a5bc9d9b4c28787606a95c6516` |

Results — every gate passed:

| Gate | Result |
| --- | --- |
| LibreLane hardening | `tt_tool` exit 0; warning profile identical in kind and count to CI (106 lint warnings, 17× CTS-0041, 10× DRT-0349) |
| Tiny Tapeout precheck | **10/10 checks pass**, including the KLayout SG13G2 DRC that the flow itself skips (`RUN_KLAYOUT_DRC 0`) |
| Functional GL from the new netlist | **10 pass / 0 fail / 4 skip** (14 total) — the predicted baseline |
| RTL regression | **14/14 pass** |
| Setup / hold, all three corners | 0 violations; setup WS +38.82 / +33.72 / +24.63 ns, hold WS +0.136 / +0.226 / +0.389 ns (fast / typ / slow) |
| DRC, LVS, antenna, power grid, routed DRC | 0 each |
| Utilisation / cells | 72.63 %; 1621 non-fill stdcells, 153 flops, 686 inverters, 57 `mux2` |
| RO + DUT structure | `u_ro_gen`, `u_ro_mat`, `u_dut`, `u_bank` hierarchies and all delay-bank instances present in the routed netlist; `boot_done` survives synthesis |

Comparison with the audited pre-fix CI run: timing moves by at most 0.04 ns (setup) and
0.003 ns (hold) at every corner — place-and-route noise — and the sequential-cell count
rises by exactly one, the `boot_done` flip-flop. The single `clkbuf_0_clk/X` max-fanout
violation reported by CI (finding F8) reproduces exactly, fanout 16 against a limit of
8, confirming that it comes from the ignored `MAX_FANOUT_CONSTRAINTS` key and not from
the F1 fix.

**Caveat on provenance.** This is a *local development* run, not a CI run: the tree was
dirty and `tt/` is a mutable checkout. It demonstrates that the flow works end to end on
the fixed RTL, but the canonical evidence for submission must still be a GitHub Actions
run of `tt-gds-action@ttihp26b` on the pushed commit, with `artifacts/run-<id>/` and its
manifest regenerated from that run.

## Canonical CI build and cross-verification (2026-09-16)

The fix was committed and pushed; GitHub Actions ran green on the tip
`0a7cd5edd8cea7a45085898f84db403c93b25af0`:

| Workflow | Run | Result |
| --- | --- | --- |
| `gds.yaml` (gds, precheck, gl_test, viewer) | [35034979531](https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/35034979531) | all four jobs `success` |
| `test.yaml` | 35034979627 | success |
| `docs.yaml` | 35034979607 | success |

The run's artifacts were downloaded and cross-checked against the local development
build above. **They are the same physical design:**

| Artifact | Local vs CI |
| --- | --- |
| Routed gate-level netlist | **byte-identical** (`e889762e…`) |
| KLayout OAS | **byte-identical** (`74c31c6e…`) |
| LEF | **byte-identical** (`337930fa…`) |
| GDS | `LayoutDiff` reports **identical** geometry (35 cells, same top cell, same DBU); the files differ only in 108 bytes of GDSII timestamp records |
| Nominal SPEF | identical except the single `*DATE` header line |
| Every signoff metric | **exactly equal**, timing to full precision (setup +38.8214 / +33.7232 / +24.6286 ns, hold +0.1356 / +0.2258 / +0.3891 ns; DRC/LVS/antenna/power-grid/route-DRC all 0; 72.6349 % utilisation; 1629 stdcells; 153 flops; 106 lint warnings; 1 max-fanout violation; 0 design violations) |
| RTL sources recorded in the CI artifact | byte-identical to the committed `src/` |
| Precheck | 10/10 pass |
| Functional GL | 10 pass / 0 fail / 4 skip |

Consequently the local full-flow verification above applies unchanged to the CI build,
and a KLayout geometric comparison rules out any layout drift that hashes alone could
not distinguish from timestamps.

The run is archived as `artifacts/run-35034979531/` with `manifest.json` /
`MANIFEST.md` generated by `tools/make_manifest.py` (24 staged files hashed; signoff,
tool and PDK identity, and headline artifact hashes recorded). `tools/common.py` now
pins `RUN_DIR`/`RUN_ID`/`GIT_COMMIT` to this build, so the experiment STA, RO-prediction
and SDF tools default to the submitted netlist and SPEF.

## Required follow-ups

1. ~~Re-harden and re-archive~~ **Done** — the canonical CI run is `35034979531` on
   commit `0a7cd5e`, and `artifacts/run-35034979531/{manifest.json,MANIFEST.md}` is
   generated from it. `test/gate_level_netlist.v` carries the new netlist
   (`e889762e…`) and the functional GL baseline is measured at 10 pass / 4 skip.
   `src/user_config.json` regenerated byte-identically. The superseded archives
   `artifacts/run-34158224984/` and run `34853386333` are retained for provenance only.
2. ~~Re-run the experiment STA / RO-prediction / SDF tooling against the new netlist~~
   **Done** — `tools/verify_safe10.sh` was re-pointed at the archived CI build
   (`TPV_RUN_DIR=artifacts/run-35034979531`) and the whole `data/safe10` package was
   regenerated from it: experiment STA, RO prediction, SDF library and sweep, prediction
   model, precheck, structural and aperture checks, RTL and GL baselines, and the
   dataset manifest. Every artifact now carries `run_id 35034979531` /
   `git_commit 0a7cd5e`. The shift is confined to place-and-route noise:

   - Primary anchor (seg3333/worst) predicted boundary: typ 30.998 → **31.153 MHz**,
     slow 19.904 → **20.008 MHz**, fast 45.126 → **45.331 MHz** (+0.5 %).
   - The count of configurations predicted to have a boundary inside 10–50 MHz is
     unchanged (24 of 96 rows).
   - SDF sweep: **one** sample of 23 flips — `nom_typ_1p20V_25C`, cfg `0x4DFF`, worst,
     32 ns period (31.25 MHz) goes from 49 errors to 0, i.e. the measured boundary moved
     by one 0.5 ns step. Every other row is bit-identical.
   - Dataset manifest now records RTL 14/14, GL 10 pass / 4 skip, precheck 10/10 against
     build commit `0a7cd5e`.

   `tools/make_local_manifest.py` gained a `TPV_ANALYSIS_HEAD` override because the
   devcontainer's bind mount can serve a stale copy of `.git/refs`, and
   `tools/verify_safe10.sh` now regenerates the RTL baseline too, so the recorded test
   counts cannot go stale again.
3. F2 decided (2026-09-16): documented host contract, no synchronizer — see the F2
   decision block. The remaining action is host-side: generate FREEZE in the chip's
   clock domain and record the per-session scope check. No RTL change, so no
   re-hardening or prediction-package re-run follows from it.
4. Correct the datasheet gaps F4 and F6; fix F8 and F9 opportunistically.
5. Fold F3/F5/F10–F12 into the post-silicon protocol as pre-declared measurement
   limits and first-silicon checks.

## Revision history

| Date | Change |
| --- | --- |
| 2026-09-16 | Initial audit; F1 fixed in `src/tt_um_echoworld424_tpv.v`, documented in `docs/info.md` / `docs/post-silicon-protocol.md` / `AGENTS.md`, covered by `test/test.py::test_uio_oe_handoff` and by the new `test/tb_pad_contention.v` pad model, which is also run in the `test` CI workflow |
| 2026-09-16 | Full submission flow re-run locally on the fixed RTL (LibreLane 3.0.5, PDK rev `c4b8b4e5…`): hardening, signoff, structure, precheck 10/10, GL 10 pass / 4 skip, RTL 14/14 — all pass; artifact hashes recorded above |
| 2026-09-16 | Fix committed and pushed as `0a7cd5e`; CI run `35034979531` green and archived as `artifacts/run-35034979531/`. CI artifact cross-checked against the local build: netlist/OAS/LEF byte-identical, GDS `LayoutDiff` identical, all signoff metrics equal to full precision (F7 resolved) |
| 2026-09-16 | F2 settled as the documented host contract (no RTL synchronizer): FREEZE HIGH-phase transition rule (LOW-phase transitions only with a proven 20 ns/10 ns margin), chip-clock-domain sourcing requirement, per-session scope check and exclusion policy added to `docs/post-silicon-protocol.md`, `docs/info.md` and `tools/emulator/README.md`; F2 status updated in the findings table, the required-follow-ups list and `AGENTS.md`. Docs-only change — no RTL, constraints, or tests touched, so the archived build `0a7cd5e` remains the current artifact |
