#!/usr/bin/env bash
# Rebuild the data/safe10 prediction package from the canonical archived build.
#
# TPV_RUN_DIR points at the CI run staged under artifacts/ (tools/common.py
# resolves nl/, spef/nom/, sdf/ and metrics.json inside it). Point the three
# TPV_* variables at a local development run instead -- a local run directory is
# its `final/` view, with resolved.json and 54-openroad-stapostpnr/ in the
# parent, as tools/make_local_manifest.py expects.
set -e
cd "$(dirname "$0")/.."
source /ttsetup/venv/bin/activate
export TPV_DATA=data/safe10
export TPV_RUN_DIR=artifacts/run-35034979531
export TPV_RUN_ID=35034979531
export TPV_BUILD_COMMIT=0a7cd5edd8cea7a45085898f84db403c93b25af0
python tools/verify_halfcycle_structure.py
python tools/run_experiment_sta.py
python tools/run_ro_predict.py
python tools/sdf/make_sdf_lib.py
python tools/run_sdfsim.py
python tools/verify_halfcycle.py
python tools/predict_model.py
python tools/run_local_precheck.py
cp artifacts/run-35034979531/nl/tt_um_echoworld424_tpv.nl.v test/gate_level_netlist.v
cd test
make clean
make
cp results.xml ../data/safe10/verification/rtl-results.xml
make clean
PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c make GATES=yes
cp results.xml ../data/safe10/verification/gl-results.xml

cd ..
python tools/make_local_manifest.py
