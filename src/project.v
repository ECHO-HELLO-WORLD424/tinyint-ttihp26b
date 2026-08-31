/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Combinational ripple-carry adder used to sum the partial-product rows.
module ripple_carry_adder #(
    parameter WIDTH = 8
) (
    input  wire [WIDTH-1:0] a,
    input  wire [WIDTH-1:0] b,
    input  wire             carry_in,
    output wire [WIDTH-1:0] sum,
    output wire             carry_out
);

  wire [WIDTH:0] carry;
  assign carry[0] = carry_in;

  genvar bit_index;
  generate
    for (bit_index = 0; bit_index < WIDTH; bit_index = bit_index + 1) begin : gen_full_adders
      assign sum[bit_index] = a[bit_index] ^ b[bit_index] ^ carry[bit_index];
      assign carry[bit_index+1] = (a[bit_index] & b[bit_index]) |
                                  (carry[bit_index] & (a[bit_index] ^ b[bit_index]));
    end
  endgenerate

  assign carry_out = carry[WIDTH];

endmodule

// 4x4 multiplier. In signed mode, the sign-row and sign-column partial
// products are complemented according to Baugh-Wooley. Adding correction bits
// at weights 4 and 7 (8'h90) then produces the 8-bit two's-complement product.
module int4_multiplier (
    input  wire [3:0] multiplicand,
    input  wire [3:0] multiplier,
    input  wire       signed_mode,
    output wire [7:0] product
);

  wire pp00 = multiplicand[0] & multiplier[0];
  wire pp10 = multiplicand[1] & multiplier[0];
  wire pp20 = multiplicand[2] & multiplier[0];
  wire pp30 = (multiplicand[3] & multiplier[0]) ^ signed_mode;

  wire pp01 = multiplicand[0] & multiplier[1];
  wire pp11 = multiplicand[1] & multiplier[1];
  wire pp21 = multiplicand[2] & multiplier[1];
  wire pp31 = (multiplicand[3] & multiplier[1]) ^ signed_mode;

  wire pp02 = multiplicand[0] & multiplier[2];
  wire pp12 = multiplicand[1] & multiplier[2];
  wire pp22 = multiplicand[2] & multiplier[2];
  wire pp32 = (multiplicand[3] & multiplier[2]) ^ signed_mode;

  wire pp03 = (multiplicand[0] & multiplier[3]) ^ signed_mode;
  wire pp13 = (multiplicand[1] & multiplier[3]) ^ signed_mode;
  wire pp23 = (multiplicand[2] & multiplier[3]) ^ signed_mode;
  wire pp33 = multiplicand[3] & multiplier[3];

  wire [7:0] partial_row_0 = {4'b0000, pp30, pp20, pp10, pp00};
  wire [7:0] partial_row_1 = {3'b000, pp31, pp21, pp11, pp01, 1'b0};
  wire [7:0] partial_row_2 = {2'b00, pp32, pp22, pp12, pp02, 2'b00};
  wire [7:0] partial_row_3 = {1'b0, pp33, pp23, pp13, pp03, 3'b000};
  wire [7:0] correction    = signed_mode ? 8'h90 : 8'h00;

  wire [7:0] sum_01;
  wire [7:0] sum_012;
  wire [7:0] sum_0123;
  wire unused_carry_0;
  wire unused_carry_1;
  wire unused_carry_2;
  wire unused_carry_3;

  ripple_carry_adder #(.WIDTH(8)) add_row_1 (
      .a(partial_row_0), .b(partial_row_1), .carry_in(1'b0),
      .sum(sum_01), .carry_out(unused_carry_0)
  );
  ripple_carry_adder #(.WIDTH(8)) add_row_2 (
      .a(sum_01), .b(partial_row_2), .carry_in(1'b0),
      .sum(sum_012), .carry_out(unused_carry_1)
  );
  ripple_carry_adder #(.WIDTH(8)) add_row_3 (
      .a(sum_012), .b(partial_row_3), .carry_in(1'b0),
      .sum(sum_0123), .carry_out(unused_carry_2)
  );
  ripple_carry_adder #(.WIDTH(8)) add_correction (
      .a(sum_0123), .b(correction), .carry_in(1'b0),
      .sum(product), .carry_out(unused_carry_3)
  );

endmodule

module tt_um_echo_hello_world424_tinyint (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,      // unused: multiplier is combinational
    input  wire       rst_n     // unused: multiplier is combinational
);

  int4_multiplier multiplier_core (
      .multiplicand(ui_in[3:0]),
      .multiplier  (ui_in[7:4]),
      .signed_mode (uio_in[4]),
      .product     (uo_out)
  );

  // All bidirectional pins remain inputs.
  assign uio_out = 8'b00000000;
  assign uio_oe  = 8'b00000000;

  // List unused inputs to prevent lint warnings.
  wire _unused = &{ena, clk, rst_n, uio_in[7:5], uio_in[3:0], 1'b0};

endmodule

`default_nettype wire
