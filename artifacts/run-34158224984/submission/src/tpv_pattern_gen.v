/*
 * Operand pattern generator. All operands are combinational decodes of the
 * pattern state (LFSR / worst-case index), which only changes at frame
 * boundaries, so each measured operation uses a stable operand triple at zero
 * register cost. The small decode cone ahead of the DUT is negligible against
 * the carry-chain delay banks.
 * sel: 0=PRBS, 1=WORST (maximum carry propagation), 2=ALT (carry-free),
 *      3=HOLD (static, minimum switching).
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`timescale 1ns / 1ps

module tpv_pattern_gen (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        load,
    input  wire [1:0]  sel,
    output wire [15:0] a,
    output wire [15:0] b,
    output wire        cin
);
  reg [15:0] lfsr;
  reg [1:0]  idx;

  /* maximal-length 16-bit Fibonacci LFSR, x^16+x^14+x^13+x^11+1 */
  wire [15:0] lfsr_nxt = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};

  reg [15:0] a_dec;
  reg [15:0] b_dec;
  reg        cin_dec;

  always @* begin
    case (sel)
      2'd0: begin  /* PRBS */
        a_dec   = lfsr_nxt;
        b_dec   = {lfsr_nxt[6:0], lfsr_nxt[15:7]};
        cin_dec = lfsr_nxt[15] ^ lfsr_nxt[7] ^ lfsr_nxt[3];
      end
      2'd1: begin  /* worst-case carry propagation */
        case (idx)
          2'd0: begin
            a_dec   = 16'hFFFF;
            b_dec   = 16'h0001;
            cin_dec = 1'b0;
          end
          2'd1: begin
            a_dec   = 16'hFFFF;
            b_dec   = 16'hFFFF;
            cin_dec = 1'b1;
          end
          2'd2: begin
            a_dec   = 16'h0FFF;
            b_dec   = 16'h0001;
            cin_dec = 1'b0;
          end
          default: begin
            a_dec   = 16'h8000;
            b_dec   = 16'h8000;
            cin_dec = 1'b1;
          end
        endcase
      end
      2'd2: begin  /* alternating, carry-free */
        if (idx[0]) begin
          a_dec   = 16'hAAAA;
          b_dec   = 16'h5555;
          cin_dec = 1'b0;
        end else begin
          a_dec   = 16'h2222;
          b_dec   = 16'h4444;
          cin_dec = 1'b0;
        end
      end
      default: begin  /* static hold */
        a_dec   = 16'h0000;
        b_dec   = 16'h0000;
        cin_dec = 1'b0;
      end
    endcase
  end

  assign a   = a_dec;
  assign b   = b_dec;
  assign cin = cin_dec;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      lfsr <= 16'hACE1;
      idx  <= 2'd0;
    end else if (load) begin
      lfsr <= lfsr_nxt;
      if (sel == 2'd1 || sel == 2'd2) idx <= idx + 2'd1;
    end
  end

endmodule
