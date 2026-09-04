/*
 * Ring-oscillator delay canaries. Both close a NAND-gated loop whose only
 * state is the loop itself; the loop node drives a ripple counter (clocked by
 * the loop, frozen when the loop stalls), giving delay telemetry as an edge
 * count over the measurement window. Loop nets carry (* keep *) so synthesis
 * preserves them.
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`timescale 1ns / 1ps

/* Tunable inverter line for RO loops (delay-bearing in simulation, so the
   loops oscillate; see tpv_inv_ro). Same tap structure as tpv_delay_line. */

module tpv_ro_line #(
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
      tpv_inv_ro u_inv (.a(node[i]), .y(node[i+1]));
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

/* Generic RO canary: one tunable inverter delay line plus a fixed tail.
   Activity-blind; its frequency tracks pure gate delay (PVT proxy).
   en/mask gate the loop itself, so the edge counter is a pure ripple
   counter in the RO domain with no cross-domain data inputs (no hold
   repair, no metastable enable sampling). */
module tpv_ro_gen (
    input  wire        rst_n,
    input  wire        en,      /* loop enable (window active) */
    input  wire [1:0]  sel,
    input  wire        mask,    /* 1 = stall loop, counter stays zero */
    output wire        ro_node,
    output reg  [9:0]  cnt
);
  wire       nand_out;
  wire       line_out;
  wire       close;

  tpv_ro_line #(
    .N_PAIRS(21),
    .TAP    (7)
  ) u_line (
    .d_in (nand_out),
    .sel  (sel),
    .d_out(line_out)
  );

  (* keep *) wire [8:0] tail;
  assign tail[0] = line_out;

  genvar i;
  generate
    for (i = 0; i < 8; i = i + 1) begin : g_tail
      tpv_inv_ro u_t (.a(tail[i]), .y(tail[i+1]));
    end
  endgenerate

  tpv_inv_ro u_close (.a(tail[8]), .y(close));
  tpv_ro_gate u_gate (
    .en      (en),
    .mask    (mask),
    .close   (close),
    .rst_n   (rst_n),
    .nand_out(nand_out)
  );

  assign ro_node = nand_out;

  always @(posedge ro_node or negedge rst_n) begin
    if (!rst_n) cnt <= 10'd0;
    else        cnt <= cnt + 10'd1;
  end

endmodule

/* Structure-matched RO canary: the loop passes through two carry-bank
   segments (delay line + full adder carrying a constant bit), mirroring the
   delay composition of DUT segments. Margin is tuned with sel. */
module tpv_ro_match (
    input  wire        rst_n,
    input  wire        en,
    input  wire [1:0]  sel,
    input  wire        mask,
    output wire        ro_node,
    output reg  [9:0]  cnt
);
  wire       nand_out;
  wire       close;
  wire       l0, l1;
  wire       f0, f1;
  wire       f0s, f1s;  /* unused FA sum outputs */

  tpv_ro_line #(
    .N_PAIRS(33),
    .TAP    (11)
  ) u_line0 (.d_in(nand_out), .sel(sel), .d_out(l0));
  tpv_fa u_f0 (.a(1'b1), .b(1'b0), .ci(l0), .s(f0s), .co(f0));
  tpv_ro_line #(
    .N_PAIRS(33),
    .TAP    (11)
  ) u_line1 (.d_in(f0), .sel(sel), .d_out(l1));
  tpv_fa u_f1 (.a(1'b1), .b(1'b0), .ci(l1), .s(f1s), .co(f1));

  /* List the unused FA sum outputs to prevent warnings */
  wire _unused = &{f0s, f1s, 1'b0};

  (* keep *) wire [8:0] tail;
  assign tail[0] = f1;

  genvar i;
  generate
    for (i = 0; i < 8; i = i + 1) begin : g_tail
      tpv_inv_ro u_t (.a(tail[i]), .y(tail[i+1]));
    end
  endgenerate

  tpv_inv_ro u_close (.a(tail[8]), .y(close));
  tpv_ro_gate u_gate (
    .en      (en),
    .mask    (mask),
    .close   (close),
    .rst_n   (rst_n),
    .nand_out(nand_out)
  );

  assign ro_node = nand_out;

  always @(posedge ro_node or negedge rst_n) begin
    if (!rst_n) cnt <= 10'd0;
    else        cnt <= cnt + 10'd1;
  end

endmodule
