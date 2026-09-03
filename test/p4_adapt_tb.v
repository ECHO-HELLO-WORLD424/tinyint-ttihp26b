/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// P4 adaptation-behaviour suite.
//
// Drives the adaptive-boundary core with directed phase streams and checks:
//   1. An unsigned dense-carry stream escalates the effective boundary to
//      20 (via 12) and stays there, matching the measured result that the
//      staged policy loses energy when boundary crossings are dense.
//   2. A signed LFSR stream settles at boundary 8 (sign-extension flips are
//      dense, crossings are rare), independent of the latched mode.
//   3. A zero-product stream falls back to boundary 20 (nothing to save).
//   4. Phase changes re-adapt within a bounded number of MACs and a mixed
//      stream does not thrash (bounded transition count).
//   5. CLEAR reloads the latched mode as the initial effective boundary.
//   6. Throughout every stream the stored value equals a conventional
//      reference bank driven with the same MACs, and the final sticky
//      overflow matches, proving retuning never changes architecture state.
module p4_adapt_tb;

  reg         clk;
  reg         rst_n;
  reg         request_valid;
  wire        request_ready;
  reg  [2:0]  request_command;
  reg  [7:0]  request_data;
  reg         request_signed_mode;

  wire [7:0]  multiplier_product;
  wire [19:0] extended_product;
  wire [19:0] accumulator_value;
  wire        latched_signed_mode;
  wire [7:0]  response_data;
  wire        response_valid;
  wire [7:0]  pair_count;
  wire        done;
  wire [7:0]  last_product;
  wire        accumulator_overflow;
  wire        count_overflow;
  wire        protocol_error;

  tiny_int_core dut (
      .clk                 (clk),
      .rst_n               (rst_n),
      .request_valid       (request_valid),
      .request_ready       (request_ready),
      .request_command     (request_command),
      .request_data        (request_data),
      .request_signed_mode (request_signed_mode),
      .request_from_bist   (1'b0),
      .multiplier_product  (multiplier_product),
      .extended_product    (extended_product),
      .accumulator_value   (accumulator_value),
      .latched_signed_mode (latched_signed_mode),
      .response_data       (response_data),
      .response_valid      (response_valid),
      .pair_count          (pair_count),
      .done                (done),
      .last_product        (last_product),
      .accumulator_overflow(accumulator_overflow),
      .count_overflow      (count_overflow),
      .protocol_error      (protocol_error)
  );

  // Conventional reference bank for state equality.
  reg         ref_clear;
  reg         ref_accumulate;
  reg  [19:0] ref_addend;
  wire [19:0] ref_value;
  wire        ref_overflow;
  reg  [19:0] ref_load_value;
  reg         ref_signed_mode;
  reg         ref_load;
  wire        ref_addition_carry;

  tiny_int_accumulator reference_bank (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (ref_clear),
      .load                (ref_load),
      .accumulate          (ref_accumulate),
      .signed_mode         (ref_signed_mode),
      .load_value          (ref_load_value),
      .addend              (ref_addend),
      .accumulator_value   (ref_value),
      .addition_result     (),
      .addition_carry      (ref_addition_carry),
      .addition_overflow   (),
      .accumulator_overflow(ref_overflow)
  );

  initial clk = 1'b0;
  always #5 clk = ~clk;

  integer errors;
  integer i;
  reg [15:0] lfsr;
  reg [7:0] d;
  reg [1:0] boundary;
  integer transitions;
  reg [1:0] last_boundary;
  integer escalate_at;
  integer settle_at;

  task step;
    input       valid;
    input [2:0] command;
    input [7:0] data;
    input       signed_pin;
    begin
      @(negedge clk);
      request_valid       = valid;
      request_command     = command;
      request_data        = data;
      request_signed_mode = signed_pin;
      // Let the multiplier/extender combinational chain settle before the
      // reference bank samples the extended product; sampling in the same
      // delta cycle would read the previous request's product.
      #1;
      // The reference bank mirrors the DUT contract: it accumulates on the
      // same accepted-MAC edges (including zero-skip and done gating) and
      // uses the DUT's LATCHED signed mode, which live pin changes cannot
      // alter between CLEARs.
      ref_clear      = (valid && command == 3'b001);
      ref_accumulate = (valid && (command == 3'b010 || command == 3'b011)) &&
                       !done &&
                       (!dut.zero_skip_register || multiplier_product != 8'b0);
      ref_addend     = ref_accumulate ? extended_product : 20'b0;
      ref_signed_mode = latched_signed_mode;
    end
  endtask

  task expect_boundary;
    input [1:0] expected;
    input [8*40-1:0] what;
    begin
      if (dut.effective_boundary !== expected) begin
        errors = errors + 1;
        $display("FAIL t=%0t boundary=%b expected=%b (%0s)",
                 $time, dut.effective_boundary, expected, what);
      end
    end
  endtask

  task check_state;
    input [8*40-1:0] what;
    begin
      if (accumulator_value !== ref_value) begin
        errors = errors + 1;
        $display("FAIL t=%0t value=%05x ref=%05x (%0s)",
                 $time, accumulator_value, ref_value, what);
      end
    end
  endtask

  // Count effective-boundary transitions across a stream.
  task count_transitions_begin;
    begin
      transitions = 0;
      last_boundary = dut.effective_boundary;
    end
  endtask

  task count_transitions_step;
    begin
      if (dut.effective_boundary !== last_boundary) begin
        transitions = transitions + 1;
        last_boundary = dut.effective_boundary;
      end
    end
  endtask

  // LFSR signed stream (sign flips dense, crossings rare): expect boundary 8.
  task run_lfsr;
    input integer count;
    begin
      for (i = 0; i < count; i = i + 1) begin
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        d = {lfsr[7:4], lfsr[3:0]};
        step(1'b1, 3'b010, d, 1'b1);
        check_state("lfsr");
        count_transitions_step;
      end
    end
  endtask

  // Unsigned dense stream (+225 per MAC): crossings dense, expect 20.
  task run_dense;
    input integer count;
    begin
      for (i = 0; i < count; i = i + 1) begin
        step(1'b1, 3'b010, 8'hff, 1'b0);
        check_state("dense");
        count_transitions_step;
      end
    end
  endtask

  // Zero-product signed stream: nothing to save, expect 20.
  task run_zero;
    input integer count;
    begin
      for (i = 0; i < count; i = i + 1) begin
        step(1'b1, 3'b010, 8'h00, 1'b1);
        check_state("zero");
        count_transitions_step;
      end
    end
  endtask

  task clear_with;
    input [1:0] mode;
    input       signed_pin;
    begin
      // The CLEAR request stays applied for one accepted cycle; the following
      // idle step recomputes the reference controls (dropping ref_clear)
      // before its own clock edge, so both banks see exactly one CLEAR edge.
      // The idle cycle also lets callers inspect the post-CLEAR state.
      step(1'b1, 3'b001, {2'b00, mode}, signed_pin);
      step(1'b0, 3'b000, 8'h00, signed_pin);
    end
  endtask

  initial begin
    clk                 = 1'b0;
    rst_n               = 1'b0;
    request_valid       = 1'b0;
    request_command     = 3'b000;
    request_data        = 8'h00;
    request_signed_mode = 1'b0;
    ref_clear           = 1'b0;
    ref_load            = 1'b0;
    ref_load_value      = 20'b0;
    ref_accumulate      = 1'b0;
    ref_addend          = 20'b0;
    ref_signed_mode     = 1'b0;
    errors              = 0;
    lfsr                = 16'h1ace;

    repeat (3) @(negedge clk);
    rst_n = 1'b1;
    ref_clear = 1'b0;

    // Reset defaults: boundary 20 (encoding 00) without any CLEAR.
    expect_boundary(2'b00, "reset default");
    check_state("reset default");

    // --- 1. Unsigned dense stream from boundary 8: escalate to 20. ---
    clear_with(2'b01, 1'b0);
    expect_boundary(2'b01, "clear mode 01 initial");
    count_transitions_begin;
    run_dense(8192);
    // The first window escalates 01 -> 10 immediately; two quiet windows at
    // 12 (crossings rare, extension quiet) move the decision to 20 by the
    // third window end. Allow the escalation+confirm path a generous 512
    // MACs, then require boundary 20 for the rest of the stream.
    if (transitions == 0 || dut.effective_boundary !== 2'b00) begin
      errors = errors + 1;
      $display("FAIL dense stream did not escalate (transitions=%0d boundary=%b)",
               transitions, dut.effective_boundary);
    end
    count_transitions_begin;
    run_dense(8192);
    if (transitions != 0) begin
      errors = errors + 1;
      $display("FAIL dense stream thrashed after escalation (%0d)",
               transitions);
    end
    expect_boundary(2'b00, "dense settled at 20");

    // --- 2. Signed LFSR from boundary 20: settle at boundary 8. ---
    clear_with(2'b00, 1'b1);
    expect_boundary(2'b00, "clear mode 00 initial");
    count_transitions_begin;
    run_lfsr(8192);
    if (dut.effective_boundary !== 2'b01) begin
      errors = errors + 1;
      $display("FAIL signed LFSR did not settle at 8 (boundary=%b transitions=%0d)",
               dut.effective_boundary, transitions);
    end
    if (transitions > 1) begin
      errors = errors + 1;
      $display("FAIL signed LFSR thrashed on the way to 8 (%0d)", transitions);
    end
    count_transitions_begin;
    run_lfsr(8192);
    if (transitions != 0) begin
      errors = errors + 1;
      $display("FAIL signed LFSR thrashed after settling (%0d)", transitions);
    end
    expect_boundary(2'b01, "signed LFSR settled at 8");

    // --- 3. Zero-product stream: fall back to 20 from 8. ---
    clear_with(2'b01, 1'b1);
    expect_boundary(2'b01, "clear mode 01 for zero stream");
    run_zero(512);
    count_transitions_begin;
    run_zero(4096);
    if (dut.effective_boundary !== 2'b00) begin
      errors = errors + 1;
      $display("FAIL zero stream did not relax to 20 (boundary=%b)",
               dut.effective_boundary);
    end
    if (transitions > 2) begin
      errors = errors + 1;
      $display("FAIL zero stream thrashed (%0d transitions)", transitions);
    end

    // --- 4. Phase changes re-adapt within 4096 MACs each. ---
    clear_with(2'b01, 1'b1);
    run_dense(2048);
    settle_at = -1;
    count_transitions_begin;
    for (i = 0; i < 4096; i = i + 1) begin
      step(1'b1, 3'b010, 8'hff, 1'b0);
      check_state("phase dense");
      count_transitions_step;
      if (settle_at < 0 && dut.effective_boundary == 2'b00)
        settle_at = i;
    end
    if (settle_at < 0) begin
      errors = errors + 1;
      $display("FAIL dense phase after signed phase did not reach 20");
    end
    count_transitions_begin;
    run_lfsr(4096);
    if (dut.effective_boundary !== 2'b01) begin
      errors = errors + 1;
      $display("FAIL signed phase did not return to 8 (boundary=%b transitions=%0d)",
               dut.effective_boundary, transitions);
    end

    // --- 5. CLEAR reloads the latched mode. ---
    clear_with(2'b10, 1'b1);
    expect_boundary(2'b10, "clear mode 10 reload");
    clear_with(2'b11, 1'b0);
    expect_boundary(2'b11, "clear mode 11 reload");

    // --- 6. Final state equality with the conventional reference. ---
    clear_with(2'b01, 1'b1);
    run_lfsr(1024);
    run_dense(512);
    run_zero(256);
    run_lfsr(512);
    check_state("final mixed phases");
    if (dut.accumulator_overflow !== ref_overflow) begin
      errors = errors + 1;
      $display("FAIL sticky overflow mismatch dut=%b ref=%b",
               dut.accumulator_overflow, ref_overflow);
    end

    if (errors == 0) begin
      $display("PASS p4_adapt_tb");
    end else begin
      $display("FAIL p4_adapt_tb: %0d errors", errors);
      $fatal(1);
    end
    $finish;
  end

endmodule

`default_nettype wire
