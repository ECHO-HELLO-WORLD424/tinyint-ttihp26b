/*
 * Timing-prediction test vehicle: low-level delay/adder primitives.
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

`timescale 1ns / 1ps

/* Inverter cell (zero simulation delay: the DUT delay banks and functional
   logic must settle instantly in RTL sim).
   For synthesis the cells are pre-mapped to library cells so the deliberate
   delay structure passes through ABC untouched - otherwise ABC merges
   inverter pairs into buffers (destroying the delay) and, for ring
   oscillators, cuts the loops entirely. */
`ifdef TPV_GDELAY
module tpv_inv_cell (
    input  wire a,
    output wire y
);
  assign y = ~a;
endmodule
`else
module tpv_inv_cell (
    input  wire a,
    output wire y
);
  sg13g2_inv_1 _cell (.A(a), .Y(y));
endmodule
`endif

/* Inverter cell for ring-oscillator loops. TPV_GDELAY is a simulation-only
   per-gate delay (ns) so the loops toggle in RTL sim. */
`ifdef TPV_GDELAY
module tpv_inv_ro (
    input  wire a,
    output wire y
);
  assign #(`TPV_GDELAY) y = ~a;
endmodule
`else
module tpv_inv_ro (
    input  wire a,
    output wire y
);
  sg13g2_inv_1 _cell (.A(a), .Y(y));
endmodule
`endif

/* Non-removable full adder (preserves the ripple-carry structure; the
   matched-RO loop passes through it, so it must also survive ABC). */
`ifdef TPV_GDELAY
module tpv_fa (
    input  wire a,
    input  wire b,
    input  wire ci,
    output wire s,
    output wire co
);
  assign s  = a ^ b ^ ci;
  assign co = (a & b) | (ci & (a ^ b));
endmodule
`else
module tpv_fa (
    input  wire a,
    input  wire b,
    input  wire ci,
    output wire s,
    output wire co
);
  wire t;
  wire u;
  wire v;

  sg13g2_xor2_1 u_x1 (.A(a), .B(b), .X(t));
  sg13g2_xor2_1 u_x2 (.A(t), .B(ci), .X(s));
  sg13g2_and2_1 u_a1 (.A(a), .B(b), .X(u));
  sg13g2_and2_1 u_a2 (.A(ci), .B(t), .X(v));
  sg13g2_or2_1  u_o1 (.A(u), .B(v), .X(co));
endmodule
`endif

/* Tap mux used inside delay lines and RO loops (must survive ABC for the
   loops): out = sel==0 ? n0 : sel==1 ? n1 : sel==2 ? n2 : n3. */
`ifdef TPV_GDELAY
module tpv_tap_mux4 (
    input  wire       n0,
    input  wire       n1,
    input  wire       n2,
    input  wire       n3,
    input  wire [1:0] sel,
    output wire       out
);
  assign out = (sel == 2'd0) ? n0 :
               (sel == 2'd1) ? n1 :
               (sel == 2'd2) ? n2 :
                               n3;
endmodule
`else
module tpv_tap_mux4 (
    input  wire       n0,
    input  wire       n1,
    input  wire       n2,
    input  wire       n3,
    input  wire [1:0] sel,
    output wire       out
);
  wire w0;
  wire w1;

  sg13g2_mux2_1 u_m0 (.X(w0), .A0(n0), .A1(n1), .S(sel[0]));
  sg13g2_mux2_1 u_m1 (.X(w1), .A0(n2), .A1(n3), .S(sel[0]));
  sg13g2_mux2_1 u_m2 (.X(out), .A0(w0), .A1(w1), .S(sel[1]));
endmodule
`endif

/* Ring-oscillator loop gate: pre-mapped to library cells for synthesis so
   ABC can never cut or restructure the loop. */
`ifdef TPV_GDELAY
module tpv_ro_gate (
    input  wire en,
    input  wire mask,
    input  wire close,
    input  wire rst_n,
    output wire nand_out
);
  assign nand_out = en & ~mask & close & rst_n;
endmodule
`else
module tpv_ro_gate (
    input  wire en,
    input  wire mask,
    input  wire close,
    input  wire rst_n,
    output wire nand_out
);
  wire m1;
  wire g1;
  wire g2;

  sg13g2_inv_1  u_im (.A(mask), .Y(m1));
  sg13g2_and2_1 u_a1 (.A(en), .B(m1), .X(g1));
  sg13g2_and2_1 u_a2 (.A(close), .B(rst_n), .X(g2));
  sg13g2_and2_1 u_a3 (.A(g1), .B(g2), .X(nand_out));
endmodule
`endif
