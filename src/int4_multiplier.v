/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

module int4_full_adder (
    input  wire a,
    input  wire b,
    input  wire carry_in,
    output wire sum,
    output wire carry_out
);

  assign sum       = a ^ b ^ carry_in;
  assign carry_out = (a & b) | (carry_in & (a ^ b));

endmodule

// Combinational ripple-carry adder used to sum the partial-product rows.
module ripple_carry_adder #(
    parameter integer WIDTH = 8
) (
    input  wire [WIDTH-1:0] a,
    input  wire [WIDTH-1:0] b,
    input  wire             carry_in,
    output wire [WIDTH-1:0] sum,
    output wire             carry_out
);

  wire [WIDTH-1:0] carry;

  genvar bit_index;
  generate
    for (bit_index = 0; bit_index < WIDTH; bit_index = bit_index + 1) begin : gen_full_adders
      if (bit_index == 0) begin : gen_first_bit
        int4_full_adder full_adder (
            .a(a[bit_index]),
            .b(b[bit_index]),
            .carry_in(carry_in),
            .sum(sum[bit_index]),
            .carry_out(carry[bit_index])
        );
      end else begin : gen_later_bits
        int4_full_adder full_adder (
            .a(a[bit_index]),
            .b(b[bit_index]),
            .carry_in(carry[bit_index-1]),
            .sum(sum[bit_index]),
            .carry_out(carry[bit_index])
        );
      end
    end
  endgenerate

  assign carry_out = carry[WIDTH-1];

endmodule

// Shared unsigned/Baugh-Wooley signed 4x4 multiplier datapath.
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

  // Baugh-Wooley correction bits at weights four and seven.
  wire [7:0] correction = signed_mode ? 8'h90 : 8'h00;

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

`default_nettype wire
