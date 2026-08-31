/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Datapath-baseline core with the request boundary used by the later MAC and
// BIST implementation. Architectural state belongs in this module.
module tiny_int_core (
    input  wire       clk,
    input  wire       rst_n,

    input  wire       request_valid,
    output wire       request_ready,
    input  wire [2:0] request_command,
    input  wire [7:0] request_data,
    input  wire       request_signed_mode,
    input  wire       request_from_bist,

    output wire [7:0] multiplier_product,
    output wire [19:0] extended_product,
    output wire [19:0] accumulator_value,
    output wire       latched_signed_mode
);

  reg signed_mode_register;

  // The core can accept one request per cycle at this implementation stage.
  // A later BIST arbiter can deassert external ready before driving this same
  // request interface with request_from_bist asserted.
  assign request_ready = rst_n;

  // Only an accepted external CLEAR samples the live mode request today. A
  // valid LOAD_BIAS_HI commit will be added here with the bias staging logic.
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      signed_mode_register <= 1'b0;
    end else if (request_valid && request_ready && !request_from_bist &&
                 (request_command == 3'b001)) begin  // CLEAR
      signed_mode_register <= request_signed_mode;
    end
  end

  assign latched_signed_mode = signed_mode_register;

  // Normal requests always use the latched mode. Internal BIST requests will
  // supply their per-vector mode without modifying the external transaction's
  // latched mode.
  wire active_signed_mode = request_from_bist ? request_signed_mode
                                               : signed_mode_register;

  int4_multiplier multiplier_core (
      .multiplicand(request_data[3:0]),
      .multiplier  (request_data[7:4]),
      .signed_mode (active_signed_mode),
      .product     (multiplier_product)
  );

  // This is the accumulator-adder input boundary. It uses the same active mode
  // as the multiplier, including per-vector BIST requests.
  product_extender product_extension (
      .product         (multiplier_product),
      .signed_mode     (active_signed_mode),
      .extended_product(extended_product)
  );

  // Reserved control boundary for the later validated command controller.
  // Keeping these controls inactive avoids introducing partial CLEAR/MAC/bias
  // semantics before their protocol, done, and error-handling rules exist.
  wire accumulator_clear      = 1'b0;
  wire accumulator_load       = 1'b0;
  wire accumulator_accumulate = 1'b0;
  wire [19:0] accumulator_load_value = 20'b0;
  wire [19:0] accumulator_addition_result;
  wire accumulator_addition_carry;
  wire accumulator_addition_overflow;
  wire accumulator_overflow;

  tiny_int_accumulator accumulator (
      .clk              (clk),
      .rst_n            (rst_n),
      .clear            (accumulator_clear),
      .load             (accumulator_load),
      .accumulate       (accumulator_accumulate),
      .signed_mode      (active_signed_mode),
      .load_value       (accumulator_load_value),
      .addend           (extended_product),
      .accumulator_value(accumulator_value),
      .addition_result  (accumulator_addition_result),
      .addition_carry   (accumulator_addition_carry),
      .addition_overflow(accumulator_addition_overflow),
      .accumulator_overflow(accumulator_overflow)
  );

  // These status signals feed the future status register and controller.
  wire _unused_accumulator_status = &{accumulator_addition_result,
                                      accumulator_addition_carry,
                                      accumulator_addition_overflow,
                                      accumulator_overflow, 1'b0};

endmodule

`default_nettype wire
