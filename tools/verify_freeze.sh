#!/usr/bin/env bash
# Re-check the RTL freeze evidence from the committed datasets.
#
# This is the fast, deterministic half of the freeze validation: it re-runs the
# analyzer fixtures, re-derives the measurement window from the RTL, re-checks
# the experiment-STA launch coverage, and rebuilds the archive summary from the
# sweep outputs.  The multi-hour transient sweeps themselves are run by
# runs/freeze-validation/stage*.sh; their raw data lives under that directory
# and their analysis JSONs are archived in data/safe10/freeze/.
set -e
cd "$(dirname "$0")/.."
REPO="$PWD"
RUNS="${TPV_FREEZE_RUNS:-runs/freeze-validation}"
export RUNS

echo "== analyzer fixtures (gate 1) =="
python3 tools/ro/test_analyse_ro_count.py

echo "== stop-transient classifier fixtures (gate 3) =="
python3 tools/ro/test_classify_stop_transient.py

echo "== wire-capacitance generator fixture (gate 2) =="
python3 tools/ro/test_add_wire_caps.py

echo "== stop-phase coverage from the archived waveforms (gate 3) =="
# The raw waveforms are git-ignored and large, so this check only runs where
# they are present; it fails if any archived window case shows a runt pulse or
# an edge after the gate closed, or if the committed dataset has drifted from
# what the tools derive from the waveforms.
if compgen -G "$RUNS/primary/cases/*.raw" >/dev/null; then
  python3 tools/ro/archive_stop_phase.py --runs "$RUNS" \
      --json "$RUNS/stop_phase_coverage.json" >/dev/null
  python3 - <<'PY'
import json, os, sys
a = json.load(open(os.environ.get("RUNS", "runs/freeze-validation") +
                   "/stop_phase_coverage.json"))
b = json.load(open("data/safe10/freeze/stop_phase_coverage.json"))
keys = ("n_cases", "n_measured", "stop_phase_spread", "n_distinct_phases",
        "total_rise_crossings", "total_runt_pulses", "total_noise_glitches",
        "total_crossings_after_close")
bad = [k for k in keys if a.get(k) != b.get(k)]
if a["total_runt_pulses"] or a["total_crossings_after_close"]:
    bad.append("runt/after-close pulses present")
if a.get("total_pulses_straddling_close") is None:
    bad.append("straddling-close count missing")
if bad:
    print("stop-phase re-check FAILED: " + ", ".join(bad))
    sys.exit(1)
print("stop-phase coverage reproduces: %d cases, %d crossings, 0 runts"
      % (a["n_cases"], a["total_rise_crossings"]))
PY
else
  echo "no archived window waveforms under $RUNS; skipping (see the record)"
fi

echo "== measurement window from the RTL (gate 2) =="
if command -v iverilog >/dev/null 2>&1; then
  python3 tools/ro/probe_ro_window.py --outdir "$RUNS/window" \
      --json "$RUNS/window/window.json" --clocks-mhz 10,50 --cfgs 0x0C00
else
  echo "iverilog not on PATH; run this inside the devcontainer"
fi

echo "== experiment-STA launch coverage (gate 4) =="
python3 tools/sta/verify_launch_coverage.py --data data/safe10

echo "== full-width wrap verdict (gate 3) =="
python3 - <<'PY'
import json, sys
w = json.load(open("data/safe10/freeze/wrap_result.json"))
w = w[0] if isinstance(w, list) and w else w
bad = []
if not w.get("count_ok"):
    bad.append("count_ok is false")
if w.get("count_error_circular") != 0:
    bad.append("circular error %r" % w.get("count_error_circular"))
if w.get("counter_wraps_inferred") != 1:
    bad.append("inferred wraps %r" % w.get("counter_wraps_inferred"))
if w.get("counter_edges_reconstructed") != w.get("ring_edges_in_window"):
    bad.append("reconstructed %r != edges %r" % (
        w.get("counter_edges_reconstructed"), w.get("ring_edges_in_window")))
if not w.get("coverage_complete"):
    bad.append("coverage incomplete")
if bad:
    print("wrap re-check FAILED: " + "; ".join(bad))
    sys.exit(1)
print("wrap: %d edges, decoded %d, %d inferred wrap, circular error 0, "
      "all stages exercised"
      % (w["ring_edges_in_window"], w["counter_final"],
         w["counter_wraps_inferred"]))
PY

echo "== ring interconnect capacitance bound =="
python3 tools/ro/analyse_loop_rc.py \
  --spef artifacts/run-35034979531/spef/nom/tt_um_echoworld424_tpv.nom.spef \
  --loops runs/count-loops \
  --liberty "${TPV_STDCELL_LIB:-$RUNS/sg13g2_stdcell_typ.lib}" \
  --json "$RUNS/loop_rc.json" >/dev/null

echo "== rebuild the archived freeze summary =="
python3 tools/ro/summarise_freeze.py --runs "$RUNS" --out data/safe10/freeze

echo
echo "freeze evidence re-checked; see data/safe10/freeze/freeze_summary.json"
