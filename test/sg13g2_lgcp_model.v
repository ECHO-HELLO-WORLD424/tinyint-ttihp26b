/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

// Simulation-only behavioral model of the IHP SG13G2 integrated clock-gating
// cell, copied verbatim from the PDK file sg13g2_stdcell.v (including the
// ihp_latch UDP it references). Synthesis must bind the real sg13g2_lgcp_1
// library cell (or a blackbox); this file must never be synthesized.

// type: gclk 
`timescale 1ns/10ps
`celldefine
module sg13g2_lgcp_1 (GCLK, GATE, CLK);
	output GCLK;
	input GATE, CLK;
	reg notifier;
	wire delayed_GATE, delayed_CLK;

	// Function
	wire int_fwire_clk, int_fwire_int_GATE;

	not (int_fwire_clk, delayed_CLK);
	ihp_latch (int_fwire_int_GATE, notifier, int_fwire_clk, delayed_GATE);
	and (GCLK, delayed_CLK, int_fwire_int_GATE);

	// Timing
	specify
		(CLK => GCLK) = 0;
		$setuphold (posedge CLK, posedge GATE, 0, 0, notifier,,, delayed_CLK, delayed_GATE);
		$setuphold (posedge CLK, negedge GATE, 0, 0, notifier,,, delayed_CLK, delayed_GATE);
		$width (posedge CLK, 0, 0, notifier);
		$width (negedge CLK, 0, 0, notifier);
	endspecify
endmodule
`endcelldefine


`ifdef _udp_def_ihp_latch_
`else
`define _udp_def_ihp_latch_
primitive ihp_latch (q, v, clk, d);
	output q;
	reg q;
	input v, clk, d;

	table
		* ? ? : ? : x;
		? 1 0 : ? : 0;
		? 1 1 : ? : 1;
		? x 0 : 0 : -;
		? x 1 : 1 : -;
		? 0 ? : ? : -;
	endtable
endprimitive
`endif
