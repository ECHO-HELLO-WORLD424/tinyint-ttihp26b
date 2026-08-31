/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Multiplier-baseline core with the request boundary used by the later MAC and
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

  // This is the input boundary for the future accumulator adder. It uses the
  // same active mode as the multiplier, including per-vector BIST requests.
  product_extender product_extension (
      .product         (multiplier_product),
      .signed_mode     (active_signed_mode),
      .extended_product(extended_product)
  );

endmodule

`default_nettype wire
