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

echo "== analyzer fixtures (gate 1) =="
python3 tools/ro/test_analyse_ro_count.py

echo "== measurement window from the RTL (gate 2) =="
if command -v iverilog >/dev/null 2>&1; then
  python3 tools/ro/probe_ro_window.py --outdir "$RUNS/window" \
      --json "$RUNS/window/window.json" --clocks-mhz 10,50 --cfgs 0x0C00
else
  echo "iverilog not on PATH; run this inside the devcontainer"
fi

echo "== experiment-STA launch coverage (gate 4) =="
python3 tools/sta/verify_launch_coverage.py --data data/safe10

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
