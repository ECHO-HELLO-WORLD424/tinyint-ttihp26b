/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Clock-gated variant of tiny_int_accumulator. Arithmetic and all port
// semantics are bit-exact with the baseline; the single 20-bit accumulator
// register and its overflow flag simply clock through one real integrated
// clock-gating cell instead of the raw clock. The caller supplies the
// core-computed bank_select; the GATE is
//   bank_select & (accumulate | clear | load)
// so a deselected bank's clock stops entirely (its addend is already
// operand-isolated to constants by the core). The ICG latch (transparent
// while CLK is low) is the glitch filter; GATE inputs are combinational
// functions of registered state and setup-timed inputs, exactly like
// standard ICG practice. No hand-built latch + AND gating is used.
module tiny_int_accumulator_icg (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        clear,
    input  wire        load,
    input  wire        accumulate,
    input  wire        signed_mode,
    input  wire [19:0] load_value,
    input  wire [19:0] addend,
    output reg  [19:0] accumulator_value,
    output wire [19:0] addition_result,
    output wire        addition_carry,
    output wire        addition_overflow,
    output reg         accumulator_overflow,
    // Core-computed selection enable and GATE observability for
    // verification; synthesis keeps them as the clock-gating enable.
    input  wire        bank_select,
    output wire        bank_gclk_en
);

  // Keep the carry bit available for later diagnostics. addition_result is the
  // modulo-2^20 value committed on an enabled accumulation edge.
  wire [20:0] full_addition = {1'b0, accumulator_value} + {1'b0, addend};

  assign addition_result = full_addition[19:0];
  assign addition_carry  = full_addition[20];

  // For signed addition, overflow occurs only when equal-sign operands produce
  // a result with the opposite sign. Unsigned overflow is the discarded carry.
  wire signed_addition_overflow =
      (accumulator_value[19] == addend[19]) &&
      (addition_result[19] != accumulator_value[19]);

  assign addition_overflow = signed_mode ? signed_addition_overflow
                                         : addition_carry;

  wire bank_gclk;

  assign bank_gclk_en = bank_select & (accumulate | clear | load);

  sg13g2_lgcp_1 bank_clock_gate (
      .GCLK(bank_gclk),
      .GATE (bank_gclk_en),
      .CLK  (clk)
  );

  // Control priority makes coincident controls deterministic. The future core
  // controller should issue them mutually exclusively after request validation.
  // A gated edge only arrives on bank_select & (accumulate | clear | load)
  // cycles, so the enable chain below stays bit-exact with the baseline.
  always @(posedge bank_gclk or negedge rst_n) begin
    if (!rst_n) begin
      accumulator_value    <= 20'b0;
      accumulator_overflow <= 1'b0;
    end else if (clear) begin
      accumulator_value    <= 20'b0;
      accumulator_overflow <= 1'b0;
    end else if (load) begin
      accumulator_value    <= load_value;
      accumulator_overflow <= 1'b0;
    end else if (accumulate) begin
      accumulator_value    <= addition_result;
      accumulator_overflow <= accumulator_overflow | addition_overflow;
    end
  end

endmodule

`default_nettype wire
