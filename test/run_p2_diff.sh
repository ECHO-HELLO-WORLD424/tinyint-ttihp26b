#!/bin/sh
# Copyright (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
#
# Two-compilation log-diff equivalence check for the ICG clock-gating
# proposal (test/p2_core_stream_tb.v). Compiles the stream driver twice —
# once against the frozen baseline core (test/p2_ref/tiny_int_core_ref.v)
# and once against the modified core with ICG banks — runs all four modes x
# the mixed/unsigned/const1/zero workloads, and requires byte-identical
# observable logs. Exits nonzero on any failure.

set -u
cd "$(dirname "$0")" || exit 1

IVERILOG=${IVERILOG:-iverilog}
OUTDIR=${OUTDIR:-/tmp/p2_core_diff}
REF_LOG="$OUTDIR/p2_ref.log"
VAR_LOG="$OUTDIR/p2_var.log"

mkdir -p "$OUTDIR" || exit 1

echo "[p2-diff] compiling reference core stream driver"
"$IVERILOG" -g2012 -DREF_CORE -o "$OUTDIR/p2b_ref" p2_core_stream_tb.v \
    p2_ref/tiny_int_core_ref.v \
    ../src/tiny_int_accumulator.v \
    ../src/tiny_int_dynamic_accumulator.v \
    ../src/int4_multiplier.v \
    ../src/product_extender.v || exit 1

echo "[p2-diff] compiling ICG variant core stream driver"
"$IVERILOG" -g2012 -o "$OUTDIR/p2b_var" p2_core_stream_tb.v \
    ../src/tiny_int_core.v \
    ../src/tiny_int_accumulator_icg.v \
    ../src/tiny_int_dynamic_accumulator_icg.v \
    ../src/int4_multiplier.v \
    ../src/product_extender.v \
    sg13g2_lgcp_model.v || exit 1

echo "[p2-diff] running reference core"
"$OUTDIR/p2b_ref" +OUT="$REF_LOG" || exit 1

echo "[p2-diff] running ICG variant core"
"$OUTDIR/p2b_var" +OUT="$VAR_LOG" || exit 1

if diff -q "$REF_LOG" "$VAR_LOG" >/dev/null; then
    LINES=$(wc -l < "$REF_LOG" | tr -d ' ')
    echo "PASS: p2 core equivalence — $LINES cycles byte-identical ($REF_LOG vs $VAR_LOG)"
    exit 0
else
    echo "FAIL: p2 core equivalence — logs differ"
    diff "$REF_LOG" "$VAR_LOG" | head -40
    exit 1
fi
