/*
 * Configurable delay line: N_PAIRS inverter pairs with taps after pair 0,
 * TAP, 2*TAP and 3*TAP (= N_PAIRS). sel picks the tap (2 bits).
 * The chain nets carry (* keep *) so synthesis preserves the deliberate
 * delay structure (double-inverter pairs are not collapsible).
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`timescale 1ns / 1ps


module tpv_delay_line #(
    parameter integer N_PAIRS = 33,
    parameter integer TAP     = 11   /* N_PAIRS must equal 3*TAP */
) (
    input  wire       d_in,
    input  wire [1:0] sel,
    output wire       d_out
);
  localparam integer N_INV = 2 * N_PAIRS;

  (* keep *) wire [N_INV:0] node;
  assign node[0] = d_in;

  genvar i;
  generate
    for (i = 0; i < N_INV; i = i + 1) begin : g_inv
      tpv_inv_cell u_inv (.a(node[i]), .y(node[i+1]));
    end
  endgenerate

  tpv_tap_mux4 u_mux (
    .n0 (node[0]),
    .n1 (node[2*TAP]),
    .n2 (node[4*TAP]),
    .n3 (node[N_INV]),
    .sel(sel),
    .out(d_out)
  );

endmodule
