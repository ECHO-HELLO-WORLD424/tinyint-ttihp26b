# f_osc dataset regeneration record (2026-09-16)

**State: resolved.** `data/safe10/spice/spice_ro.csv` is now **revision 3**,
measured on the current build (commit `0a7cd5e`, CI run `35034979531`, netlist
sha256 `18a5657c…`). Revision 2 is archived under `data/safe10/spice/rev2/`.

## What the regeneration found

The first attempt used the ring-only deck and disagreed with the validated
counter-inclusive deck by up to 2.5x for some tap selections. Three separate
causes were identified and all three were fixed or explained:

1. **A driver bug.** `run_ro_spice_case.py` guessed the loop-node net name
   (`_1351_/CLK` vs `_1347_/CLK` between builds) and silently saved a
   non-existent node, so the rawfile had no loop waveform for half the cases.
   The loop node now comes from the extraction metadata, and the deck also saves
   it through a 1 GΩ sense branch as a second name.
2. **A window artifact.** Runs sized to a handful of ring periods gave a
   mean-interval frequency that depended on which intervals the window happened
   to contain. With a uniform 30-period window the rings are clean: 20/24 cases
   have a coefficient of variation of the rising-edge intervals below 0.01.
3. **A ring-only deck defect, unresolved.** In the ring-only extraction the loop
   can close through the wrong tap for `can_sel=2`: the same case measured
   215.3 MHz and 499.4 MHz in two runs of the same deck, and the resulting
   f_osc table was non-monotonic in `can_sel` for 5 of 6 corner/canary groups,
   which is not physical. The counter-inclusive deck is monotonic in every group
   and agrees with revision 2 within 1.42%. The f_osc dataset is therefore
   measured with the counter-inclusive deck, and the ring-only sweep
   (`tools/ro/sweep_ro_spice.py`) should not be used for f_osc until this is
   understood.

## Multi-mode configurations (recorded, not hidden)

Four cases — `nom_typ_1p20V_25C` and `nom_slow_1p08V_125C`, `ro_mat`, `can_sel`
2 and 3 — oscillate in more than one mode (interval cv 0.38–0.58). They are the
four longest loops in the design (108–144 ns period). Their revision-2 values
are retained in revision 3 and flagged in the CSV (`cv`, `n_modes`, `note`), and
their multi-mode behaviour is timestep-independent (checked at 5 ps and 2 ps).
Characterising them properly needs an interval-distribution or modal-period
convention, which is a decision about how the canary is read out rather than a
simulation fix.

## Tooling added

- `tools/ro/analyse_ro_intervals.py` — period distribution, jitter, and mode
  detection (used for the `cv`/`n_modes` columns).
- `tools/ro/run_ro_count_case.py` — the counter-inclusive deck used for
  revision 3.
