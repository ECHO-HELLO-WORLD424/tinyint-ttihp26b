/*
 * Independent oracle: bit-serial reference adder. start loads the operands
 * through a step-selected bit mux (no copy registers); 16 shift steps plus a
 * carry flush happen over the following 17 clk cycles; acc then holds the
 * correct 17-bit {cout, sum} until the next start. The per-cycle path is a
 * single adder bit plus a 16:1 mux, far shorter than the DUT path.
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`timescale 1ns / 1ps

module tpv_checker (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        en,        /* 0 = freeze (measurement paused) */
    input  wire        start,
    input  wire [15:0] a,
    input  wire [15:0] b,
    input  wire        cin,
    output reg  [16:0] acc,       /* correct {cout, sum}, valid when done */
    output reg         done
);
  reg [4:0] step;
  reg       cry;

  wire a_bit = a[step[3:0]];
  wire b_bit = b[step[3:0]];
  wire bit_s = a_bit ^ b_bit ^ cry;
  wire bit_c = (a_bit & b_bit) | (cry & (a_bit ^ b_bit));

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      acc  <= 17'd0;
      cry  <= 1'b0;
      step <= 5'd0;
      done <= 1'b0;
    end else if (start) begin
      acc  <= 17'd0;
      cry  <= cin;
      step <= 5'd0;
      done <= 1'b0;
    end else if (en && !done) begin
      if (step == 5'd16) begin
        acc  <= {cry, acc[16:1]};  /* flush final carry */
        done <= 1'b1;
      end else begin
        acc  <= {bit_s, acc[16:1]};
        cry  <= bit_c;
        step <= step + 5'd1;
      end
    end
  end

endmodule
