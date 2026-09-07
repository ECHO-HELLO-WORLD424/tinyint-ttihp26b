set -e
cd "$(dirname "$0")/.."
source /ttsetup/venv/bin/activate
export TPV_DATA=data/safe10
export TPV_RUN_DIR=src/runs/dev-safe10/final
export TPV_RUN_ID=local-dev-safe10
export TPV_BUILD_COMMIT=7b20196bb74195649679fae6313a891712e87458
python tools/verify_halfcycle_structure.py
python tools/run_experiment_sta.py
python tools/run_ro_predict.py
python tools/sdf/make_sdf_lib.py
python tools/run_sdfsim.py
python tools/verify_halfcycle.py
python tools/predict_model.py
python tools/run_local_precheck.py
cp src/runs/dev-safe10/final/nl/tt_um_echoworld424_tpv.nl.v test/gate_level_netlist.v
cd test
make clean
PDK_ROOT=/home/vscode/ttsetup/pdk/ciel/ihp-sg13g2/versions/c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c make GATES=yes
cp results.xml ../data/safe10/verification/gl-results.xml

cd ..
python tools/make_local_manifest.py
