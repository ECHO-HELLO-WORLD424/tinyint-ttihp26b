#!/bin/sh
# Run the P4 adaptive-boundary equivalence matrix.
#
# Each matrix cell compiles the shared driver twice (golden composite core
# from test/p4_ref plus unchanged leaves; proposed adaptive-boundary core plus
# tiny_int_unified_accumulator), runs both simulations for the same MODE and
# WORKLOAD plusargs, and requires byte-identical cycle logs. The only
# permitted difference between the two cores is the upper nibble of the held
# READ selector 3'b110 response (the effective-boundary report), which the
# driver masks to 'Z' in both runs; workloads 5/6 latch zero_skip_register so
# the skipped-MAC path is covered in every mode as well.
#
# Usage: test/run_p4_equiv.sh
#
# Set P4_LOG_DIR to keep the cycle logs of failing (or all) cells for
# inspection; by default logs live in a throwaway temporary directory.
set -u

cd "$(dirname "$0")" || exit 2

IVERILOG=${IVERILOG:-iverilog}
VVP=${VVP:-vvp}

if [ -n "${P4_LOG_DIR:-}" ]; then
    LOG_DIR=${P4_LOG_DIR}
else
    LOG_DIR=$(mktemp -d /tmp/p4_equiv.XXXXXX) || exit 2
fi
mkdir -p "$LOG_DIR" || exit 2
echo "P4 equivalence logs: $LOG_DIR"

fail=0

"$IVERILOG" -g2012 -DREF_CORE -o "$LOG_DIR/ref.vvp" \
    p4_core_equiv_tb.v p4_ref/tiny_int_core_ref.v \
    ../src/int4_multiplier.v ../src/product_extender.v \
    ../src/tiny_int_accumulator.v ../src/tiny_int_dynamic_accumulator.v || exit 2
"$IVERILOG" -g2012 -o "$LOG_DIR/var.vvp" \
    p4_core_equiv_tb.v ../src/tiny_int_core.v \
    ../src/tiny_int_unified_accumulator.v \
    ../src/int4_multiplier.v ../src/product_extender.v || exit 2

for mode in 0 1 2 3; do
    for workload in 0 1 2 3 4 5 6; do
        "$VVP" "$LOG_DIR/ref.vvp" +MODE=$mode +WORKLOAD=$workload \
            +OUT="$LOG_DIR/ref_m${mode}_w${workload}.log" > "$LOG_DIR/ref_m${mode}_w${workload}.out" || fail=1
        "$VVP" "$LOG_DIR/var.vvp" +MODE=$mode +WORKLOAD=$workload \
            +OUT="$LOG_DIR/var_m${mode}_w${workload}.log" > "$LOG_DIR/var_m${mode}_w${workload}.out" || fail=1
        if diff -q "$LOG_DIR/ref_m${mode}_w${workload}.log" \
                   "$LOG_DIR/var_m${mode}_w${workload}.log" > /dev/null; then
            echo "PASS mode=$mode workload=$workload"
        else
            echo "FAIL mode=$mode workload=$workload (first differences):"
            diff "$LOG_DIR/ref_m${mode}_w${workload}.log" \
                 "$LOG_DIR/var_m${mode}_w${workload}.log" | head -10
            fail=1
        fi
    done
done

if [ "$fail" -eq 0 ]; then
    echo "PASS p4 equivalence matrix: 28/28 cells byte-identical"
else
    echo "FAIL p4 equivalence matrix"
fi
exit $fail
