/*
 * Device under test: 16-bit segmented ripple-carry adder with tunable carry
 * delay banks. Each 4-bit segment ripples through 4 full adders; the carry
 * between segments and the final carry-out pass through a tpv_delay_line
 * selected by seg_sel[2*k +: 2]. This makes the critical path length
 * programmable while keeping operand-dependent carry propagation.
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`timescale 1ns / 1ps

module tpv_rca16 (
    input  wire [15:0] a,
    input  wire [15:0] b,
    input  wire        cin,
    input  wire [7:0]  seg_sel,  /* {sel3, sel2, sel1, sel0} */
    output wire [15:0] sum,
    output wire        cout
);
  wire [2:0] bank_out;  /* carry after inter-segment banks 0..2 */

  genvar k, j;
  generate
    for (k = 0; k < 4; k = k + 1) begin : g_seg
      wire [4:0] sc;      /* carries within the segment */
      wire       sci;     /* carry into the segment */
      wire       bank_dout;

      if (k == 0) begin : g_in
        assign sci = cin;
      end else begin : g_in
        assign sci = bank_out[k-1];
      end

      assign sc[0] = sci;

      for (j = 0; j < 4; j = j + 1) begin : g_fa
        tpv_fa u_fa (
          .a (a[4*k + j]),
          .b (b[4*k + j]),
          .ci(sc[j]),
          .s (sum[4*k + j]),
          .co(sc[j+1])
        );
      end

      tpv_delay_line #(
        .N_PAIRS(48),
        .TAP    (16)
      ) u_bank (
        .d_in (sc[4]),
        .sel  (seg_sel[2*k +: 2]),
        .d_out(bank_dout)
      );

      if (k == 3) begin : g_cout
        assign cout = bank_dout;
      end else begin : g_cout
        assign bank_out[k] = bank_dout;
      end
    end
  endgenerate

endmodule
