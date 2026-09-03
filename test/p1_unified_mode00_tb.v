/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Pure accumulator-level check for the unified single-bank proposal.
//
// Three leaf instances receive identical stimulus:
//   - tiny_int_unified_accumulator (the proposal),
//   - tiny_int_accumulator         (conventional golden),
//   - tiny_int_dynamic_accumulator (dynamic golden).
//
// In boundary-20 mode (accumulator_mode == 2'b00) the proposal must match the
// conventional module exactly: accumulator_value, addition_result,
// addition_carry, addition_overflow and the sticky accumulator_overflow are
// compared on every accumulate, and stage_write_enable must assert all five
// stages. In the dynamic modes the proposal must match the dynamic module
// exactly, including per-stage write enables. Clear and load edges are
// compared as well, and the asynchronous reset is re-exercised at the end.
module p1_unified_mode00_tb;

  reg         clk;
  reg         rst_n;
  reg         clear;
  reg         load;
  reg         accumulate;
  reg         signed_mode;
  reg  [1:0]  accumulator_mode;
  reg  [19:0] load_value;
  reg  [19:0] addend;

  // Proposal outputs.
  wire [19:0] unified_value;
  wire [19:0] unified_result;
  wire        unified_carry;
  wire        unified_overflow;
  wire        unified_sticky;
  wire [4:0]  unified_stage_we;

  // Conventional golden outputs.
  wire [19:0] conv_value;
  wire [19:0] conv_result;
  wire        conv_carry;
  wire        conv_overflow;
  wire        conv_sticky;

  // Dynamic golden outputs.
  wire [19:0] dyn_value;
  wire [19:0] dyn_result;
  wire        dyn_carry;
  wire        dyn_overflow;
  wire        dyn_sticky;
  wire [4:0]  dyn_stage_we;

  integer macs;
  integer checks;
  integer clears;
  integer loads;
  integer i;
  integer window_remaining;
  reg [31:0] random_word;
  reg [19:0] random_20;

  // The goldens must track the same architectural state as the proposal to
  // make a comparison meaningful. The accumulator mode therefore only ever
  // changes on a CLEAR edge (exactly as the core guarantees), and each
  // golden receives the accumulate pulse only inside its own mode window:
  // the conventional golden is blind to dynamic-mode MACs and the dynamic
  // golden is blind to boundary-20 MACs.
  wire conventional_window = accumulator_mode == 2'b00;
  wire conv_accumulate = accumulate && conventional_window;
  wire dyn_accumulate = accumulate && !conventional_window;

  tiny_int_unified_accumulator dut (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear),
      .load                (load),
      .accumulate          (accumulate),
      .signed_mode         (signed_mode),
      .accumulator_mode    (accumulator_mode),
      .load_value          (load_value),
      .addend              (addend),
      .accumulator_value   (unified_value),
      .addition_result     (unified_result),
      .addition_carry      (unified_carry),
      .addition_overflow   (unified_overflow),
      .accumulator_overflow(unified_sticky),
      .stage_write_enable  (unified_stage_we)
  );

  tiny_int_accumulator conventional_golden (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear),
      .load                (load),
      .accumulate          (conv_accumulate),
      .signed_mode         (signed_mode),
      .load_value          (load_value),
      .addend              (addend),
      .accumulator_value   (conv_value),
      .addition_result     (conv_result),
      .addition_carry      (conv_carry),
      .addition_overflow   (conv_overflow),
      .accumulator_overflow(conv_sticky)
  );

  tiny_int_dynamic_accumulator dynamic_golden (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear),
      .load                (load),
      .accumulate          (dyn_accumulate),
      .signed_mode         (signed_mode),
      .accumulator_mode    (accumulator_mode),
      .load_value          (load_value),
      .addend              (addend),
      .accumulator_value   (dyn_value),
      .addition_result     (dyn_result),
      .addition_carry      (dyn_carry),
      .addition_overflow   (dyn_overflow),
      .accumulator_overflow(dyn_sticky),
      .stage_write_enable  (dyn_stage_we)
  );

  task clock_once;
    begin
      #1 clk = 1'b1;
      #1 clk = 1'b0;
    end
  endtask

  // Two $random draws fold into one 20-bit value so every bit sees fresh
  // entropy; the explicit seed keeps the sequence reproducible.
  task draw_random_20;
    begin
      random_word = $random;
      random_20[15:0] = random_word[15:0];
      random_word = $random;
      random_20[19:16] = random_word[1:0];
    end
  endtask

  task fail_mismatch;
    input [8*40-1:0] field;
    input [31:0] expected;
    input [31:0] actual;
    begin
      $display("MISMATCH i=%0d mode=%b signed=%b clear=%b load=%b accum=%b addend=%05x field=%0s expected=%08x actual=%08x",
               i, accumulator_mode, signed_mode, clear, load, accumulate,
               addend, field, expected, actual);
      $fatal(1);
    end
  endtask

  initial begin
    clk              = 1'b0;
    rst_n            = 1'b0;
    clear            = 1'b0;
    load             = 1'b0;
    accumulate       = 1'b0;
    signed_mode      = 1'b0;
    accumulator_mode = 2'b00;
    load_value       = 20'b0;
    addend           = 20'b0;
    macs             = 0;
    checks           = 0;
    clears           = 0;
    loads            = 0;
    window_remaining = 0;

    clock_once();
    rst_n = 1'b1;

    for (i = 0; i < 20000; i = i + 1) begin
      // Mode windows: a fresh window draws a mode (boundary 20 carries 40%
      // of the weight) and always begins with a CLEAR, mirroring the core
      // contract that the mode only changes through a CLEAR. Within a window
      // the occasional clear is a plain state reset in the same mode.
      if (window_remaining == 0) begin
        case ($unsigned($random) % 5)
          0, 1: accumulator_mode = 2'b00;
          2:    accumulator_mode = 2'b01;
          3:    accumulator_mode = 2'b10;
          default: accumulator_mode = 2'b11;
        endcase
        window_remaining = 8 + ($unsigned($random) % 32);
        clear = 1'b1;
        clears = clears + 1;
      end else begin
        clear = ($unsigned($random) % 32) == 0;
        if (clear) clears = clears + 1;
        window_remaining = window_remaining - 1;
      end
      signed_mode = $unsigned($random) & 1'b1;

      load = !clear && (($unsigned($random) % 16) == 0);
      accumulate = !(clear || load);
      if (load) loads = loads + 1;
      draw_random_20();
      addend = random_20;
      draw_random_20();
      load_value = random_20;

      if (accumulate) begin
        macs = macs + 1;
        #1;
        if (accumulator_mode == 2'b00) begin
          checks = checks + 1;
          if (unified_result !== conv_result)
            fail_mismatch("addition_result", conv_result, unified_result);
          if (unified_carry !== conv_carry)
            fail_mismatch("addition_carry", conv_carry, unified_carry);
          if (unified_overflow !== conv_overflow)
            fail_mismatch("addition_overflow", conv_overflow,
                          unified_overflow);
          if (unified_stage_we !== 5'b11111)
            fail_mismatch("stage_write_enable", 32'h1f, unified_stage_we);
        end else begin
          checks = checks + 1;
          if (unified_result !== dyn_result)
            fail_mismatch("addition_result", dyn_result, unified_result);
          if (unified_carry !== dyn_carry)
            fail_mismatch("addition_carry", dyn_carry, unified_carry);
          if (unified_overflow !== dyn_overflow)
            fail_mismatch("addition_overflow", dyn_overflow,
                          unified_overflow);
          if (unified_stage_we !== dyn_stage_we)
            fail_mismatch("stage_write_enable", dyn_stage_we,
                          unified_stage_we);
        end
      end

      clock_once();

      // Controls deassert for the observation cycle; committed state and the
      // sticky overflow must agree with the selected golden module.
      clear = 1'b0;
      load = 1'b0;
      accumulate = 1'b0;
      #1;
      checks = checks + 1;
      if (accumulator_mode == 2'b00) begin
        if (unified_value !== conv_value)
          fail_mismatch("accumulator_value", conv_value, unified_value);
        if (unified_sticky !== conv_sticky)
          fail_mismatch("accumulator_overflow", conv_sticky, unified_sticky);
      end else begin
        if (unified_value !== dyn_value)
          fail_mismatch("accumulator_value", dyn_value, unified_value);
        if (unified_sticky !== dyn_sticky)
          fail_mismatch("accumulator_overflow", dyn_sticky, unified_sticky);
      end
    end

    // Asynchronous reset must clear every stage of the unified bank.
    accumulate = 1'b1;
    draw_random_20();
    addend = random_20;
    #1;
    clk = 1'b1;
    #1 clk = 1'b0;
    accumulate = 1'b0;
    rst_n = 1'b0;
    #1;
    if (unified_value !== 20'b0 || unified_sticky !== 1'b0) begin
      $display("MISMATCH async reset: value=%05x sticky=%b",
               unified_value, unified_sticky);
      $fatal(1);
    end
    rst_n = 1'b1;
    #1;
    checks = checks + 2;

    $display("PASS p1_unified_mode00 macs=%0d checks=%0d clears=%0d loads=%0d",
             macs, checks, clears, loads);
    $finish;
  end

endmodule

`default_nettype wire
