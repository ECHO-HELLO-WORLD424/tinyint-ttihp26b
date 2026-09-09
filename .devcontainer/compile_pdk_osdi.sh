#!/bin/sh
# Compile the IHP SG13G2 Verilog-A models (PSP103) to OSDI for ngspice.
#
# The PDK is downloaded by CIEL on first use, so its osdi/ directory does not
# exist in a freshly built image.  This script is idempotent: it does nothing
# when the OSDI files are already present, and it never fails the container
# start (a missing PDK just means "run this again after the PDK is installed").
#
# Used by docs/ro-spice-validation.md; see also .devcontainer/Dockerfile.

set -u

PDK_ROOT="${PDK_ROOT:-/home/vscode/ttsetup/pdk}"
PDK="${PDK:-ihp-sg13g2}"

if ! command -v openvaf-r >/dev/null 2>&1; then
    echo "compile_pdk_osdi: openvaf-r not installed; skipping" >&2
    exit 0
fi

# Locate the CIEL-managed PDK version directory (newest if several).
VA_DIR=""
for d in "$PDK_ROOT"/ciel/"$PDK"/versions/*/"$PDK"/libs.tech/verilog-a; do
    [ -d "$d" ] && VA_DIR="$d"
done
if [ -z "$VA_DIR" ]; then
    echo "compile_pdk_osdi: no PDK under $PDK_ROOT/ciel/$PDK/versions; skipping" >&2
    exit 0
fi

OSDI_DIR="$(dirname "$VA_DIR")/ngspice/osdi"
if [ -f "$OSDI_DIR/psp103.osdi" ] && [ -f "$OSDI_DIR/psp103_nqs.osdi" ]; then
    echo "compile_pdk_osdi: OSDI models already present in $OSDI_DIR"
    exit 0
fi

echo "compile_pdk_osdi: compiling PSP103 Verilog-A models in $VA_DIR"
mkdir -p "$OSDI_DIR"
cd "$VA_DIR" || exit 0
# The PDK ships the script without the execute bit.
sh ./openvaf-compile-va.sh || {
    echo "compile_pdk_osdi: openvaf-compile-va.sh failed" >&2
    exit 0
}
ls -l "$OSDI_DIR"
