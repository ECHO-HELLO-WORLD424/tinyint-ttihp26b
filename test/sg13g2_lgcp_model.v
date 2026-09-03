/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

// Simulation-only behavioral model of the IHP SG13G2 integrated clock-gating
// cell (sg13g2_lgcp_1). This is a FUNCTIONAL-ONLY model: it intentionally
// omits the PDK specify block, the ihp_latch UDP and the notifier timing
// checks. Those constructs are not portable across simulators - Icarus
// Verilog 12 (the CI simulator) does not support timing checks and leaves
// the specify-block delayed_CLK/delayed_GATE wires undriven, which X-corrupts
// the latch clock and GCLK through the verbatim PDK model - and the RTL
// regression runs without SDF annotation, where every check limit is 0.
// Synthesis must bind the real sg13g2_lgcp_1 library cell (or a blackbox);
// this file must never be synthesized.
//
// Function (identical to the PDK cell): GATE is latched while CLK is low and
// held while CLK is high, so GCLK = CLK & latched GATE only rises on a CLK
// edge where GATE was already asserted (glitch-free positive-edge ICG).

module sg13g2_lgcp_1 (GCLK, GATE, CLK);
	output GCLK;
	input GATE, CLK;

	reg latched_gate;

	// Level-sensitive latch: transparent while CLK is low, opaque while high.
	always @(*) begin
		if (!CLK)
			latched_gate = GATE;
	end

	assign GCLK = CLK & latched_gate;

endmodule
