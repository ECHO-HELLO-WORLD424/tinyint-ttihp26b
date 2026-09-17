#!/usr/bin/env python3
"""Build the archived RTL-freeze validation dataset from the run directories.

Inputs (all produced by the tools in this directory):

  Window boundary probe      runs/freeze-validation/window/window.json
  Analyzer fixtures          data/safe10/count/analyzer_fixtures.json
  Primary window sweep       runs/freeze-validation/primary/{ro_count.csv,json}
  Matrix sweep               runs/freeze-validation/matrix/{ro_count.csv,json}
  Carry coverage             runs/freeze-validation/carry/carry_result.json
  Control cases              runs/freeze-validation/control/control_result.json
  Timestep convergence       runs/freeze-validation/convergence/*.json
  Wire-capacitance bound     runs/freeze-validation/wirecap_sensitivity.json

Outputs: `data/safe10/freeze/`
  freeze_summary.json        machine-readable verdict per gate
  primary_windows.csv/.json  the 12 primary cases x 3 startups, per case
  matrix_windows.csv         the full 24-case counter matrix
  repeatability.csv          per-configuration spread across startup phases
  coverage.csv               per-bit coverage across all analysed windows
  convergence.csv            5 ps vs 2 ps comparison
  manifest.json              hashes of every archived file and tool

Usage:
  summarise_freeze.py [--runs runs/freeze-validation] [--out data/safe10/freeze]
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))

PRIMARY_COLS = ["tag", "corner", "canary", "can_sel", "win_sel", "tclk_ns",
                "phase", "status", "accepted", "counter_final", "ring_edges",
                "f_count_mhz", "f_steady_mhz", "cv", "coverage_complete",
                "rate_stable", "unexercised_bits", "wall_s"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def load_rows(path):
    return load_json(path, []) or []


def sweep_rows(outdir):
    """Rows for one sweep directory: the per-case JSONs, newest wins.

    The sweeps resume and are invoked more than once per directory (different
    clock periods, different subsets), so each invocation overwrites
    `ro_count.json` with only its own cases.  Merging the per-case analysis
    JSONs is the complete view.
    """
    rows = {}
    case_dir = os.path.join(outdir, "cases")
    if os.path.isdir(case_dir):
        for fn in sorted(os.listdir(case_dir)):
            if not fn.endswith(".json"):
                continue
            d = load_json(os.path.join(case_dir, fn))
            if not isinstance(d, dict) or "case" not in d:
                continue
            c = d["case"]
            rows[d.get("tag", fn[:-5])] = dict(
                tag=d.get("tag"), corner=c.get("corner"),
                canary=c.get("canary"), can_sel=c.get("can_sel"),
                win_sel=c.get("win_sel"), tclk_ns=c.get("tclk_ns"),
                phase=c.get("phase"), tstep_ps=c.get("tstep_ps"),
                status=d.get("status"),
                accepted=bool(d.get("count_ok") and d.get("settled")),
                counter_final=d.get("counter_final"),
                ring_edges=d.get("ring_edges_in_window"),
                f_count_mhz=d.get("f_count_mhz"),
                f_steady_mhz=d.get("steady_f_mhz"),
                cv=d.get("steady_std_over_mean"),
                coverage_complete=d.get("coverage_complete"),
                rate_stable=d.get("rate_stable"),
                unexercised_bits=d.get("unexercised_bits"),
                wall_s=d.get("wall_s"),
                settle_after_gate_close_ns=(
                    None if d.get("last_bit_transition_ns") is None
                    else round(d["last_bit_transition_ns"] -
                               (d.get("t_en_fall_ns") or 0), 3)))
    if rows:
        return sorted(rows.values(), key=lambda r: r["tag"] or "")
    return load_rows(os.path.join(outdir, "ro_count.json"))


def repeatability(rows):
    """Spread of the window count across startup phases, per configuration."""
    groups = {}
    for r in rows:
        key = (r["corner"], r["canary"], r["can_sel"], r["win_sel"],
               r["tclk_ns"])
        groups.setdefault(key, []).append(r)
    out = []
    for key, rs in sorted(groups.items()):
        counts = [r.get("counter_final") for r in rs
                  if r.get("counter_final") is not None]
        freqs = [r.get("f_count_mhz") for r in rs if r.get("f_count_mhz")]
        if not counts:
            continue
        spread = max(counts) - min(counts)
        out.append(dict(
            corner=key[0], canary=key[1], can_sel=key[2], win_sel=key[3],
            tclk_ns=key[4], n_startups=len(counts),
            counts=";".join(str(c) for c in sorted(counts)),
            count_min=min(counts), count_max=max(counts), count_spread=spread,
            count_spread_pct=round(100.0 * spread / (sum(counts) / len(counts)),
                                   4) if sum(counts) else None,
            f_mean_mhz=round(sum(freqs) / len(freqs), 3) if freqs else None,
            f_spread_pct=round(100.0 * (max(freqs) - min(freqs)) /
                               (sum(freqs) / len(freqs)), 4) if freqs else None,
            statuses=";".join(sorted({str(r.get("status")) for r in rs}))))
    return out


def coverage_rows(rows):
    out = []
    for r in rows:
        unex = r.get("unexercised_bits")
        if isinstance(unex, str):
            unex = [int(x) for x in unex.split(",") if x.strip()]
        out.append(dict(tag=r["tag"], corner=r["corner"], canary=r["canary"],
                        can_sel=r["can_sel"], tclk_ns=r["tclk_ns"],
                        phase=r["phase"], ring_edges=r.get("ring_edges"),
                        coverage_complete=r.get("coverage_complete"),
                        highest_exercised_bit=(
                            None if not r.get("ring_edges") else
                            max([b for b in range(16)
                                 if r["ring_edges"] // (2 ** b) > 0],
                                default=None)),
                        unexercised_bits=";".join(str(b) for b in (unex or [])),
                        status=r.get("status")))
    return out


def write_csv(path, rows, cols=None):
    if not rows:
        open(path, "w").write("")
        return
    cols = cols or list(rows[0].keys())
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=os.path.join(REPO, "runs/freeze-validation"))
    ap.add_argument("--out", default=os.path.join(REPO, "data/safe10/freeze"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    R = a.runs

    probe = load_json(os.path.join(R, "window/window.json"), [])
    fixtures = load_json(os.path.join(REPO, "data/safe10/count",
                                      "analyzer_fixtures.json"), {})
    primary = sweep_rows(os.path.join(R, "primary"))
    matrix = sweep_rows(os.path.join(R, "matrix"))
    carry = load_json(os.path.join(R, "carry/carry_result.json"), [])
    control = load_json(os.path.join(R, "control/control_result.json"), [])
    wirecap = load_json(os.path.join(R, "wirecap_sensitivity.json"), {})
    # The corrected re-run (after the generator unit fix): the only valid
    # measurement of the lumped wire-capacitance effect.
    wirecap_fixed = load_json(os.path.join(
        REPO, "data/safe10/freeze/wirecap_sensitivity_corrected.json"), {})
    rc_runs = wirecap_fixed.get("runs", [])
    rc_ok = bool(rc_runs) and all(
        r.get("count_ok") and str(r.get("status", "")).startswith("ok")
        for r in rc_runs)
    # Timestep convergence: the 5/10/20/40 ps probe plus the 2 ps probe.
    convergence = load_rows(os.path.join(R, "timestep_probe.json")) + \
        load_rows(os.path.join(R, "timestep_probe_2ps.json")) + \
        load_rows(os.path.join(R, "timestep2/timestep_probe.json")) + \
        load_rows(os.path.join(R, "convergence/ro_count.json"))

    # Cross-check the window deck against the independently validated f_osc
    # dataset (revision 3): the deck is a different structure with a different
    # stopping condition, so agreement is a real consistency check.
    fosc = {}
    fosc_csv = os.path.join(REPO, "data/safe10/spice/spice_ro.csv")
    if os.path.exists(fosc_csv):
        for row in csv.DictReader(open(fosc_csv)):
            try:
                fosc[(row["corner"], row["canary"], int(row["can_sel"]))] = \
                    float(row["f_osc_mhz"])
            except (KeyError, ValueError):
                continue
    for r in primary + matrix:
        ref = fosc.get((r.get("corner"), r.get("canary"), r.get("can_sel")))
        r["f_osc_dataset_mhz"] = round(ref, 3) if ref else None
        r["f_osc_delta_pct"] = (round(100.0 * (r["f_steady_mhz"] - ref) / ref, 3)
                                if ref and r.get("f_steady_mhz") else None)

    rep = repeatability(primary)
    cov = coverage_rows(primary + matrix)
    json.dump(carry, open(os.path.join(a.out, "carry.json"), "w"), indent=1,
              default=str)
    json.dump(control, open(os.path.join(a.out, "control.json"), "w"),
              indent=1, default=str)
    for rows, name in ((primary, "primary_windows"), (matrix, "matrix_windows"),
                       (rep, "repeatability"), (cov, "coverage"),
                       (convergence, "convergence")):
        write_csv(os.path.join(a.out, name + ".csv"), rows)
        json.dump(rows, open(os.path.join(a.out, name + ".json"), "w"),
                  indent=1)

    # ------------------------------------------------------------- verdicts --
    gate1_ok = bool(fixtures.get("passed"))
    primary_accepted = [r for r in primary if r.get("accepted")]
    primary_unstable = [r for r in primary if r.get("rate_stable") is False]
    carry_ok = bool(carry) and all(r.get("count_ok") for r in carry) and \
        all((r.get("per_bit_coverage") or {}) and
            all(c.get("exercised") for c in r["per_bit_coverage"].values())
            for r in carry)
    max_spread_pct = max((r["count_spread_pct"] or 0) for r in rep) if rep \
        else None
    gate2_ok = bool(primary) and len(primary_accepted) == len(primary) and \
        (max_spread_pct is not None and max_spread_pct <= 1.0)
    settled = [r for r in primary + matrix if r.get("accepted")]
    settle_frac = None
    if settled:
        # Settling must fit the two-external-clock readout interval.
        ok = 0
        for r in settled:
            allow = 2 * r["tclk_ns"] if r.get("tclk_ns") else None
            s = r.get("settle_after_gate_close_ns")
            if allow and s is not None and s <= allow:
                ok += 1
        settle_frac = round(ok / len(settled), 4)

    recheck = load_json(os.path.join(REPO, "data/safe10/freeze",
                                     "analyzer_recheck.json"), {})
    wirecap_fixture = load_json(os.path.join(
        REPO, "data/safe10/freeze/wirecap_generation_fixture.json"), {})
    stop_phase = load_json(os.path.join(REPO, "data/safe10/freeze",
                                        "stop_phase_coverage.json"), {})
    stop_sweep = load_json(os.path.join(REPO, "data/safe10/freeze",
                                        "stop_phase_sweep.json"), {})
    # The full-width wrap run: the same fast/shortest-ring configuration with the
    # gate open long enough to cross 0xFFFF (regenerated from its stored rawfile
    # by tools/ro/reanalyse_carry_result.py after the analyzer fixes).
    wrap = load_json(os.path.join(REPO, "data/safe10/freeze",
                                  "wrap_result.json"), [])
    wrap = wrap[0] if isinstance(wrap, list) and wrap else {}
    summary = dict(
        purpose="RTL freeze validation (gates 1-3 of docs/rtl-freeze-checklist.md)",
        analyzer_recheck={k: recheck.get(k) for k in
                          ("mode", "n_cases", "all_levels_valid",
                           "invalid_level_cases", "verdict_changes")},
        wirecap_generation_fixture=dict(
            n_cases=len(wirecap_fixture.get("cases", [])),
            passed=wirecap_fixture.get("passed"),
            failures=wirecap_fixture.get("failures", []))
        if wirecap_fixture else {},
        # Gate 3 stop-phase evidence, from the archived waveforms: the phase at
        # gate close and the amplitude of the stop transient.  The claim being
        # checked is that no marginal-width clock pulse reaches the counter.
        stop_phase_coverage={k: stop_phase.get(k) for k in
                             ("n_cases", "n_measured", "stop_phase_min",
                              "stop_phase_max", "stop_phase_spread",
                              "n_distinct_phases", "total_rise_crossings",
                              "total_runt_pulses", "total_noise_glitches",
                              "total_crossings_after_close")}
        if stop_phase else {},
        stop_phase_sweep={k: stop_sweep.get(k) for k in
                          ("n_phases", "periods", "period_ns",
                           "all_count_ok", "all_settled", "all_levels_valid",
                           "statuses")}
        if stop_sweep else {},
        window_probe=probe,
        gate1=dict(analyzer_fixtures_passed=gate1_ok,
                   n_fixtures=len(fixtures.get("fixtures", [])),
                   failures=fixtures.get("failures", [])),
        gate2=dict(n_primary_runs=len(primary),
                   n_accepted=len(primary_accepted),
                   max_count_spread_pct=max_spread_pct,
                   acceptance_tolerance_pct=1.0,
                   n_unstable_rate_cases=len(primary_unstable),
                   unstable_cases=[r["tag"] for r in primary_unstable],
                   # The window/count question is answered; the wire-RC
                   # limitation is bounded by simulation once the corrected
                   # sensitivity run has counted every case.
                   rc_sensitivity_run_valid=bool(rc_ok),
                   verdict=("pass_rc_sensitivity_simulated"
                            if gate2_ok and rc_ok else
                            "pass_rc_sensitivity_open" if gate2_ok
                            else "incomplete")),
        gate3=dict(carry_runs=len(carry), carry_all_count_ok=carry_ok,
                   control_runs=len(control),
                   control_all_count_ok=bool(control) and
                   all(r.get("count_ok") for r in control),
                   settle_within_readout_fraction=settle_frac,
                   matrix_runs=len(matrix),
                   matrix_acceptance=(
                       "pass" if matrix and all(r.get("accepted")
                                                for r in matrix)
                       else "incomplete"),
                   # The stop-phase question: every archived window case was
                   # classified by pulse amplitude, so `runt_pulses == 0` means
                   # no marginal-width clock pulse reached the counter at any of
                   # the phases tested; the targeted sweep then varies the phase
                   # directly.  `wrap` is the full 0xFFFF wrap run.
                   stop_phase_spread=stop_phase.get("stop_phase_spread"),
                   stop_phase_distinct=stop_phase.get("n_distinct_phases"),
                   stop_phase_crossings=stop_phase.get("total_rise_crossings"),
                   stop_phase_runt_pulses=stop_phase.get("total_runt_pulses"),
                   stop_phase_crossings_after_close=stop_phase.get(
                       "total_crossings_after_close"),
                   stop_phase_sweep_phases=stop_sweep.get("n_phases"),
                   stop_phase_sweep_all_count_ok=stop_sweep.get("all_count_ok"),
                   wrap_run_present=bool(wrap),
                   wrap_count_ok=wrap.get("count_ok"),
                   wrap_edges=wrap.get("ring_edges_in_window"),
                   wrap_counter_final=wrap.get("counter_final"),
                   wrap_wraps_inferred=wrap.get("counter_wraps_inferred"),
                   wrap_circular_error=wrap.get("count_error_circular"),
                   wrap_coverage_complete=wrap.get("coverage_complete"),
                   wrap_gate_open_ns=wrap.get("gate_open_ns")),
        # Interconnect: what the SPEF says the cell-level decks omit, the
        # invalid revision-1 injection attempt, and the corrected re-run.
        interconnect=dict(
            measured=load_json(os.path.join(R, "loop_rc.json"), {}),
            injection_attempt=dict(
                tool="tools/ro/add_wire_caps.py + run_wirecap_sensitivity.py",
                outcome="revision-1 decks are invalid: add_wire_caps.py wrote "
                        "the capacitance in pF without a SPICE scale suffix, "
                        "and an unsuffixed capacitor value is in farads, so "
                        "every injected capacitor was 10**12 too large and the "
                        "loop stalled. The generator now emits `p` and is "
                        "covered by tools/ro/test_add_wire_caps.py",
                superseded_runs=wirecap.get("runs", []),
                comparison=wirecap.get("comparison", [])),
            corrected_run=dict(
                dataset="data/safe10/freeze/wirecap_sensitivity_corrected.json",
                tool="tools/ro/add_wire_caps.py (units fixed) + "
                     "tools/ro/run_wirecap_sensitivity.py --jobs 8",
                window_ns=wirecap_fixed.get("window_ns"),
                tstep_ps=wirecap_fixed.get("tstep_ps"),
                all_runs_counted=bool(rc_ok),
                comparison=wirecap_fixed.get("comparison", []))),
        convergence=convergence)
    json.dump(summary, open(os.path.join(a.out, "freeze_summary.json"), "w"),
              indent=1)

    # Write the human-readable tables *before* hashing the archive: the
    # manifest must describe the files as they are left on disk, and hashing
    # first left `freeze_tables.md` with its previous revision's digest.
    write_markdown(os.path.join(a.out, "freeze_tables.md"), probe, primary,
                   matrix, rep, cov, carry, control, convergence, wirecap,
                   summary)

    # ------------------------------------------------------------ manifest --
    manifest = dict(archived={}, tools={})
    for fn in sorted(os.listdir(a.out)):
        p = os.path.join(a.out, fn)
        if os.path.isfile(p) and fn != "manifest.json":
            manifest["archived"][fn] = sha256(p)
    for t in ("run_ro_count_case.py", "analyse_ro_count.py",
              "analyse_ro_intervals.py", "sweep_ro_count.py",
              "run_ro_carry_test.py", "probe_ro_window.py",
              "add_wire_caps.py", "run_wirecap_sensitivity.py",
              "analyse_loop_rc.py", "test_analyse_ro_count.py",
              "test_add_wire_caps.py", "recheck_archived_counts.py",
              # Gate 3 stop-phase evidence: the phase at gate close, the
              # stop-transient amplitude classification, the targeted sweep and
              # the archival tool that builds stop_phase_coverage.json.
              "measure_stop_phase.py", "classify_stop_transient.py",
              "sweep_stop_phase.py", "archive_stop_phase.py",
              "reanalyse_carry_result.py",
              "summarise_freeze.py"):
        p = os.path.join(HERE, t)
        if os.path.exists(p):
            # Repo-relative keys: a bare basename does not tell a reviewer
            # where the tool lives.
            manifest["tools"][os.path.relpath(p, REPO)] = sha256(p)
    for t in ("tools/sta/experiment_sta.tcl", "tools/run_experiment_sta.py",
              "tools/sta/verify_launch_coverage.py", "tools/common.py",
              "tools/verify_freeze.sh"):
        p = os.path.join(REPO, t)
        if os.path.exists(p):
            manifest["tools"][t] = sha256(p)
    # Build inputs the frozen RTL is identified by, and the decks the archived
    # cases were actually run from (raw waveforms stay under runs/).
    manifest["build_inputs"] = {}
    for rel in ("src/tt_um_echoworld424_tpv.v", "src/tpv_rca16.v",
                "src/tpv_delay_line.v", "src/tpv_cells.v", "src/tpv_checker.v",
                "src/tpv_pattern_gen.v", "src/tpv_ro_canary.v",
                "src/config.json", "src/pnr.sdc", "info.yaml",
                "artifacts/run-35034979531/nl/tt_um_echoworld424_tpv.nl.v",
                "artifacts/run-35034979531/spef/nom/"
                "tt_um_echoworld424_tpv.nom.spef"):
        p = os.path.join(REPO, rel)
        if os.path.exists(p):
            manifest["build_inputs"][rel] = sha256(p)
    # The transient source: the Magic spiceextraction the loops were cut from.
    for rel in ("runs/ci-35034979531/GDS_logs/runs/wokwi/final/spice/"
                "tt_um_echoworld424_tpv.spice",
                "runs/wokwi/final/spice/tt_um_echoworld424_tpv.spice"):
        p = os.path.join(REPO, rel)
        if os.path.exists(p):
            manifest["build_inputs"][rel] = sha256(p)
            break
    manifest["decks"] = {}
    for sub in ("primary/cases", "matrix/cases", "carry", "control",
                "timestep", "timestep2"):
        d = os.path.join(REPO, "runs/freeze-validation", sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".sp"):
                manifest["decks"][f"{sub}/{fn}"] = sha256(os.path.join(d, fn))
    json.dump(manifest, open(os.path.join(a.out, "manifest.json"), "w"),
              indent=1)
    print(json.dumps({k: summary[k] for k in ("gate1", "gate2", "gate3")},
                     indent=1))
    print("archived " + a.out)
    return 0


def _md_table(rows, cols):
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return "_(no data)_\n"
    out = ["| " + " | ".join(cols) + " |",
           "| " + " | ".join("---" for _ in cols) + " |"]
    for r in rows:
        out.append("| " + " | ".join(
            "" if r.get(c) is None else str(r.get(c)) for c in cols) + " |")
    return "\n".join(out) + "\n"


def write_markdown(path, probe, primary, matrix, rep, cov, carry, control,
                   convergence, wirecap, summary):
    L = ["# RTL freeze validation — generated tables", "",
         "Generated by `tools/ro/summarise_freeze.py` from the JSON/CSV data",
         "archived next to it.  Do not edit by hand.", ""]
    L += ["## Measurement window derived from the RTL", ""]
    L += [_md_table([dict(cfg=p.get("cfg"), clk_period_ns=p.get("period_ns"),
                          ro_en_rise_cycle=(p.get("ro_en_rise") or {}).get("cycle"),
                          win_done_cycle=(p.get("win_done_rise") or {}).get("cycle"),
                          ro_en_fall_cycle=(p.get("ro_en_fall") or {}).get("cycle"),
                          cycles_open=p.get("cycles_open"),
                          open_ns=p.get("open_duration_ns"))
                     for p in (probe or [])],
                    ["cfg", "clk_period_ns", "ro_en_rise_cycle",
                     "win_done_cycle", "ro_en_fall_cycle", "cycles_open",
                     "open_ns"])]
    L += ["", "## Primary window cases", ""]
    L += [_md_table(primary,
                    ["corner", "canary", "can_sel", "tclk_ns", "phase",
                     "status", "counter_final", "ring_edges", "f_count_mhz",
                     "cv", "coverage_complete", "rate_stable",
                     "f_osc_dataset_mhz", "f_osc_delta_pct"])]
    L += ["", "## Startup repeatability", ""]
    L += [_md_table(rep, ["corner", "canary", "tclk_ns", "n_startups",
                          "counts", "count_spread", "count_spread_pct",
                          "f_mean_mhz", "statuses"])]
    L += ["", "## Per-bit coverage", ""]
    L += [_md_table(cov, ["tag", "ring_edges", "highest_exercised_bit",
                          "unexercised_bits", "coverage_complete", "status"])]
    L += ["", "## Counter matrix (all can_sel)", ""]
    L += [_md_table(matrix, ["corner", "canary", "can_sel", "tclk_ns", "status",
                             "counter_final", "ring_edges", "coverage_complete"])]
    L += ["", "## Carry coverage", ""]
    L += [_md_table([dict(kind=r.get("kind"), corner=r.get("corner"),
                          canary=r.get("canary"), can_sel=r.get("can_sel"),
                          status=r.get("status"), edges=r.get("ring_edges_in_window"),
                          count=r.get("counter_final"),
                          coverage=r.get("coverage_complete"),
                          high_bit=max([b for b in range(16)
                                        if (r.get("ring_edges_in_window") or 0) // (2 ** b) > 0],
                                       default=None))
                     for r in (carry or [])],
                    ["kind", "corner", "canary", "can_sel", "status", "edges",
                     "count", "coverage", "high_bit"])]
    L += ["", "## Control cases", ""]
    L += [_md_table([dict(kind=r.get("kind"), status=r.get("status"),
                          edges=r.get("ring_edges_in_window"),
                          count=r.get("counter_final"),
                          settled=r.get("settled"), count_ok=r.get("count_ok"))
                     for r in (control or [])],
                    ["kind", "status", "edges", "count", "settled", "count_ok"])]
    L += ["", "## Timestep convergence", ""]
    L += [_md_table([dict(corner=r.get("corner"), canary=r.get("canary"),
                          can_sel=r.get("can_sel"), tstep_ps=r.get("tstep_ps"),
                          status=r.get("status"), edges=r.get("edges"),
                          f_mhz=r.get("f_mhz"), cv=r.get("cv"),
                          count_ok=r.get("count_ok"))
                     for r in (convergence or [])],
                    ["corner", "canary", "can_sel", "tstep_ps", "status",
                     "edges", "f_mhz", "cv", "count_ok"])]
    L += ["", "## Wire-capacitance sensitivity (lumped SPEF C added)", ""]
    L += [_md_table(wirecap or [], ["corner", "canary", "can_sel",
                                    "f_nocap_mhz", "f_wirecap_mhz", "delta_pct",
                                    "cv_nocap", "cv_wirecap"])]
    L += ["", "## Gate verdicts", "", "```json",
          json.dumps({k: summary[k] for k in ("gate1", "gate2", "gate3")},
                     indent=1), "```", ""]
    open(path, "w").write("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
