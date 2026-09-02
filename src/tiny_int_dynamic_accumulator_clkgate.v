/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Clock-gated prototype of the bit-exact 20-bit dynamic accumulator.
//
// This is a functional prototype to quantify the energy headroom that is left
// on the table by the tapeout's synchronous data gating. It keeps the exact
// five-nibble datapath and bit-exact write pattern of
// tiny_int_dynamic_accumulator, but replaces the D-input write-enable muxes
// with latch-based integrated clock gating: each stage's clock is shut off
// unless that stage is allowed to write in the current cycle.
//
//   enable_N  = clear | load | (accumulate & stage_update_event[N])
//   gclk_N    = clk & D-latch(enable_N)      // glitch-free ICG pattern
//
// Stage 0/1 are active in every dynamic mode and are gated only by
// accumulate/clear/load. Stages 2..4 are additionally gated by their carry or
// borrow event, so their flip-flop clocks stop toggling (and the flip-flops
// stop consuming internal clock power) on cycles that do not reach them. The
// sticky overflow bit is gated by accumulate/clear/load.
//
// This is a prototype only: it is not hardened, the gated clocks have not been
// through CTS, and no clock-gating cell is used. The RTL is written so that a
// real ICG cell (or OpenROAD ICG insertion) can replace the latch+AND.
module tiny_int_dynamic_accumulator_clkgate (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        clear,
    input  wire        load,
    input  wire        accumulate,
    input  wire        signed_mode,
    input  wire [1:0]  accumulator_mode,
    input  wire [19:0] load_value,
    input  wire [19:0] addend,
    output wire [19:0] accumulator_value,
    output wire [19:0] addition_result,
    output wire        addition_carry,
    output wire        addition_overflow,
    output reg         accumulator_overflow,
    output wire [4:0]  stage_write_enable
);

  reg [3:0] stage_0;
  reg [3:0] stage_1;
  reg [3:0] stage_2;
  reg [3:0] stage_3;
  reg [3:0] stage_4;

  assign accumulator_value = {stage_4, stage_3, stage_2, stage_1, stage_0};

  // The first eight bits are active in every dynamic mode.
  wire [4:0] stage_0_addition =
      {1'b0, stage_0} + {1'b0, addend[3:0]};
  wire [4:0] stage_1_addition =
      {1'b0, stage_1} + {1'b0, addend[7:4]} + stage_0_addition[4];

  // Isolate the operands of optional active-region adders (same as baseline).
  wire stage_2_active = accumulator_mode != 2'b01;
  wire stage_3_active = (accumulator_mode == 2'b11) ||
                        (accumulator_mode == 2'b00);
  wire [3:0] stage_2_active_addend = stage_2_active ? addend[11:8] : 4'b0;
  wire       stage_2_active_carry = stage_2_active ?
                                             stage_1_addition[4] : 1'b0;
  wire [4:0] stage_2_addition =
      {1'b0, stage_2} + {1'b0, stage_2_active_addend} +
      stage_2_active_carry;
  wire [3:0] stage_3_active_addend = stage_3_active ? addend[15:12] : 4'b0;
  wire       stage_3_active_carry = stage_3_active ?
                                             stage_2_addition[4] : 1'b0;
  wire [4:0] stage_3_addition =
      {1'b0, stage_3} + {1'b0, stage_3_active_addend} +
      stage_3_active_carry;

  function automatic [4:0] increment_stage;
    input [3:0] value;
    begin
      increment_stage[3:0] = value + 1'b1;
      increment_stage[4]   = value == 4'hf;
    end
  endfunction

  function automatic [4:0] decrement_stage;
    input [3:0] value;
    begin
      decrement_stage[3:0] = value - 1'b1;
      decrement_stage[4]   = value == 4'h0;
    end
  endfunction

  reg [3:0] next_stage_0;
  reg [3:0] next_stage_1;
  reg [3:0] next_stage_2;
  reg [3:0] next_stage_3;
  reg [3:0] next_stage_4;
  reg [4:0] stage_update_event;
  reg       carry_out;
  reg       increment_event;
  reg       decrement_event;
  reg       event_propagates;
  reg [4:0] cold_stage_result;

  // Construct the exact next value while retaining per-stage write intent.
  // Identical to the baseline; the write intent feeds the clock gate instead
  // of a D-input enable mux.
  always @(*) begin
    next_stage_0     = stage_0_addition[3:0];
    next_stage_1     = stage_1_addition[3:0];
    next_stage_2     = stage_2;
    next_stage_3     = stage_3;
    next_stage_4     = stage_4;
    stage_update_event = 5'b00011;
    carry_out          = 1'b0;
    increment_event    = 1'b0;
    decrement_event    = 1'b0;
    event_propagates   = 1'b0;
    cold_stage_result  = 5'b0;

    case (accumulator_mode)
      2'b01: begin : dynamic_8_next
        increment_event = !addend[19] && stage_1_addition[4];
        decrement_event =  addend[19] && !stage_1_addition[4];

        if (increment_event) begin
          cold_stage_result = increment_stage(stage_2);
        end else if (decrement_event) begin
          cold_stage_result = decrement_stage(stage_2);
        end
        if (increment_event || decrement_event) begin
          next_stage_2         = cold_stage_result[3:0];
          stage_update_event[2] = 1'b1;
          event_propagates     = cold_stage_result[4];
        end

        if (event_propagates) begin
          if (increment_event) begin
            cold_stage_result = increment_stage(stage_3);
          end else begin
            cold_stage_result = decrement_stage(stage_3);
          end
          next_stage_3          = cold_stage_result[3:0];
          stage_update_event[3] = 1'b1;
          event_propagates      = cold_stage_result[4];
        end

        if (event_propagates) begin
          if (increment_event) begin
            cold_stage_result = increment_stage(stage_4);
          end else begin
            cold_stage_result = decrement_stage(stage_4);
          end
          next_stage_4          = cold_stage_result[3:0];
          stage_update_event[4] = 1'b1;
          event_propagates      = cold_stage_result[4];
        end

        carry_out = addend[19] ? !event_propagates : event_propagates;
      end

      2'b10: begin : dynamic_12_next
        next_stage_2          = stage_2_addition[3:0];
        stage_update_event[2] = 1'b1;
        increment_event = !addend[19] && stage_2_addition[4];
        decrement_event =  addend[19] && !stage_2_addition[4];

        if (increment_event) begin
          cold_stage_result = increment_stage(stage_3);
        end else if (decrement_event) begin
          cold_stage_result = decrement_stage(stage_3);
        end
        if (increment_event || decrement_event) begin
          next_stage_3          = cold_stage_result[3:0];
          stage_update_event[3] = 1'b1;
          event_propagates      = cold_stage_result[4];
        end

        if (event_propagates) begin
          if (increment_event) begin
            cold_stage_result = increment_stage(stage_4);
          end else begin
            cold_stage_result = decrement_stage(stage_4);
          end
          next_stage_4          = cold_stage_result[3:0];
          stage_update_event[4] = 1'b1;
          event_propagates      = cold_stage_result[4];
        end

        carry_out = addend[19] ? !event_propagates : event_propagates;
      end

      default: begin : dynamic_16_next
        next_stage_2          = stage_2_addition[3:0];
        next_stage_3          = stage_3_addition[3:0];
        stage_update_event[2] = 1'b1;
        stage_update_event[3] = 1'b1;
        increment_event = !addend[19] && stage_3_addition[4];
        decrement_event =  addend[19] && !stage_3_addition[4];

        if (increment_event) begin
          cold_stage_result = increment_stage(stage_4);
        end else if (decrement_event) begin
          cold_stage_result = decrement_stage(stage_4);
        end
        if (increment_event || decrement_event) begin
          next_stage_4          = cold_stage_result[3:0];
          stage_update_event[4] = 1'b1;
          event_propagates      = cold_stage_result[4];
        end

        carry_out = addend[19] ? !event_propagates : event_propagates;
      end
    endcase
  end

  assign addition_result = {next_stage_4, next_stage_3, next_stage_2,
                            next_stage_1, next_stage_0};
  assign addition_carry = carry_out;
  assign stage_write_enable = {5{accumulate}} & stage_update_event;

  wire signed_addition_overflow =
      (accumulator_value[19] == addend[19]) &&
      (addition_result[19] != accumulator_value[19]);
  assign addition_overflow = signed_mode ? signed_addition_overflow
                                         : addition_carry;

  // ---- integrated clock gating ------------------------------------------
  // A level-sensitive D latch (sg13g2_dlhq_1, transparent while GATE is high)
  // tracks each write-enable during the low half of the clock and holds it
  // while clk is high; the stage clock is the AND of clk with the latched
  // enable. This is the standard glitch-free ICG structure. During reset the
  // data is forced to zero so the gates are closed and the asynchronous-reset
  // flip-flops are unaffected. GATE = ~clk keeps the latch transparent while
  // clk is low.
  wire clk_low = ~clk;
  wire en_01_d = rst_n ? (clear | load | accumulate) : 1'b0;
  wire en_2_d  = rst_n ? (clear | load | (accumulate & stage_update_event[2]))
                       : 1'b0;
  wire en_3_d  = rst_n ? (clear | load | (accumulate & stage_update_event[3]))
                       : 1'b0;
  wire en_4_d  = rst_n ? (clear | load | (accumulate & stage_update_event[4]))
                       : 1'b0;

  wire en_01;
  wire en_2;
  wire en_3;
  wire en_4;
  wire en_ovf;

  sg13g2_dlhq_1 icg_latch_01 (.D(en_01_d), .GATE(clk_low), .Q(en_01));
  sg13g2_dlhq_1 icg_latch_2  (.D(en_2_d),  .GATE(clk_low), .Q(en_2));
  sg13g2_dlhq_1 icg_latch_3  (.D(en_3_d),  .GATE(clk_low), .Q(en_3));
  sg13g2_dlhq_1 icg_latch_4  (.D(en_4_d),  .GATE(clk_low), .Q(en_4));
  sg13g2_dlhq_1 icg_latch_ovf(.D(en_01_d), .GATE(clk_low), .Q(en_ovf));

  wire gclk_01  = clk & en_01;
  wire gclk_2   = clk & en_2;
  wire gclk_3   = clk & en_3;
  wire gclk_4   = clk & en_4;
  wire gclk_ovf = clk & en_ovf;

  // ---- state flip-flops (same reset/clear/load priority as the baseline) --
  always @(posedge gclk_01 or negedge rst_n) begin
    if (!rst_n) begin
      stage_0 <= 4'b0;
      stage_1 <= 4'b0;
    end else if (clear) begin
      stage_0 <= 4'b0;
      stage_1 <= 4'b0;
    end else if (load) begin
      stage_0 <= load_value[3:0];
      stage_1 <= load_value[7:4];
    end else begin
      stage_0 <= next_stage_0;
      stage_1 <= next_stage_1;
    end
  end

  always @(posedge gclk_2 or negedge rst_n) begin
    if (!rst_n) begin
      stage_2 <= 4'b0;
    end else if (clear) begin
      stage_2 <= 4'b0;
    end else if (load) begin
      stage_2 <= load_value[11:8];
    end else begin
      stage_2 <= next_stage_2;
    end
  end

  always @(posedge gclk_3 or negedge rst_n) begin
    if (!rst_n) begin
      stage_3 <= 4'b0;
    end else if (clear) begin
      stage_3 <= 4'b0;
    end else if (load) begin
      stage_3 <= load_value[15:12];
    end else begin
      stage_3 <= next_stage_3;
    end
  end

  always @(posedge gclk_4 or negedge rst_n) begin
    if (!rst_n) begin
      stage_4 <= 4'b0;
    end else if (clear) begin
      stage_4 <= 4'b0;
    end else if (load) begin
      stage_4 <= load_value[19:16];
    end else begin
      stage_4 <= next_stage_4;
    end
  end

  always @(posedge gclk_ovf or negedge rst_n) begin
    if (!rst_n) begin
      accumulator_overflow <= 1'b0;
    end else if (clear) begin
      accumulator_overflow <= 1'b0;
    end else if (load) begin
      accumulator_overflow <= 1'b0;
    end else begin
      accumulator_overflow <= accumulator_overflow | addition_overflow;
    end
  end

endmodule

`default_nettype wire