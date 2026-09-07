/*
 * Independent combinational reference adder. No intentional delay cells.
 * Operands are held for a 19-cycle frame; the result is compared only at the
 * next frame boundary, long after the DUT's half-cycle capture. Synthesis
 * maps this arithmetic separately from the pre-mapped DUT carry banks.
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */
`default_nettype none `timescale 1ns / 1ps

module tpv_checker (
    input wire [15:0] a,
    input wire [15:0] b,
    input wire cin,
    output wire [16:0] acc
);
  assign acc = {1'b0, a} + {1'b0, b} + {16'd0, cin};
endmodule
