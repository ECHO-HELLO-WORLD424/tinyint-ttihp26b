/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Extend the raw 8-bit multiplier result to the accumulator datapath width.
// Signed products preserve their two's-complement value; unsigned products
// are zero-extended. This combinational boundary is kept separate so the
// accumulator and overflow detector can be added without changing the
// multiplier leaf.
module product_extender (
    input  wire [7:0]  product,
    input  wire        signed_mode,
    output wire [19:0] extended_product
);

  assign extended_product = signed_mode ? {{12{product[7]}}, product}
                                        : {12'b0, product};

endmodule

`default_nettype wire
