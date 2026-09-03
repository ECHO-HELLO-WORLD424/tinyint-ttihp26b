/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Clock-gated variant of tiny_int_dynamic_accumulator. Arithmetic, port
// semantics and clear > load > accumulate priority are bit-exact with the
// baseline; only the register clocks change. Every clock gate is a real
// integrated clock-gating cell (sg13g2_lgcp_1), never a hand-built
// latch + AND structure:
//   - One bank-level ICG gates stage 0/1 and the overflow flag. Its GATE is
//     accumulate | clear | load; the caller folds bank selection into those
//     inputs, so an unselected bank's clock stops entirely.
//   - Stages 2..4 additionally pass through their own ICG cascaded from the
//     bank-gated clock, keeping a single clock root per bank for CTS. Their
//     GATE is clear | load | (accumulate & stage_update_event[k]), reusing
//     the baseline stage_update_event, so a cold nibble only clocks when a
//     carry/borrow event actually reaches it. Stages 0/1 and the overflow
//     flag toggle on nearly every MAC, so further gating them is overhead.
// The ICG latch (transparent while CLK is low) is the glitch filter; the
// GATE inputs are combinational functions of registered state and
// setup-timed inputs, exactly like standard ICG practice.
module tiny_int_dynamic_accumulator_icg (
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
    output wire [4:0]  stage_write_enable,
    // GATE observability for verification; synthesis keeps them as the
    // clock-gating enables.
    output wire        bank_gclk_en,
    output wire [4:2]  stage_gclk_en
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

  // Isolate the operands of optional active-region adders. In dynamic-8 the
  // stage-2 adder inputs are constant; in dynamic-8/12 the stage-3 inputs are
  // constant. Cold-stage event logic below remains available in those modes.
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
  // A cold stage is written only when a carry/borrow event reaches it.
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
        // 2'b11 is the legal dynamic-16 mode. Treating an accidental 2'b00
        // value as dynamic-16 keeps this leaf's arithmetic deterministic.
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

  // Clock gating structure. bank_gclk_en covers every state write of this
  // bank (clear and load must open every gate in the cycles they assert);
  // the caller already folds bank selection into accumulate/clear/load.
  assign bank_gclk_en = accumulate | clear | load;
  assign stage_gclk_en[2] = clear | load |
                            (accumulate & stage_update_event[2]);
  assign stage_gclk_en[3] = clear | load |
                            (accumulate & stage_update_event[3]);
  assign stage_gclk_en[4] = clear | load |
                            (accumulate & stage_update_event[4]);

  wire bank_gclk;
  wire stage_2_gclk;
  wire stage_3_gclk;
  wire stage_4_gclk;

  sg13g2_lgcp_1 bank_clock_gate (
      .GCLK(bank_gclk),
      .GATE (bank_gclk_en),
      .CLK  (clk)
  );
  sg13g2_lgcp_1 stage_2_clock_gate (
      .GCLK(stage_2_gclk),
      .GATE (stage_gclk_en[2]),
      .CLK  (bank_gclk)
  );
  sg13g2_lgcp_1 stage_3_clock_gate (
      .GCLK(stage_3_gclk),
      .GATE (stage_gclk_en[3]),
      .CLK  (bank_gclk)
  );
  sg13g2_lgcp_1 stage_4_clock_gate (
      .GCLK(stage_4_gclk),
      .GATE (stage_gclk_en[4]),
      .CLK  (bank_gclk)
  );

  // Hot nibbles and the overflow flag ride the bank-gated clock. Clear/load
  // intentionally write them; the GATE already guarantees a clock edge only
  // on clear/load/accumulate cycles, so the enable chain below stays
  // bit-exact with the baseline.
  always @(posedge bank_gclk or negedge rst_n) begin
    if (!rst_n) begin
      stage_0              <= 4'b0;
      stage_1              <= 4'b0;
      accumulator_overflow <= 1'b0;
    end else if (clear) begin
      stage_0              <= 4'b0;
      stage_1              <= 4'b0;
      accumulator_overflow <= 1'b0;
    end else if (load) begin
      stage_0              <= load_value[3:0];
      stage_1              <= load_value[7:4];
      accumulator_overflow <= 1'b0;
    end else if (accumulate) begin
      stage_0              <= next_stage_0;
      stage_1              <= next_stage_1;
      accumulator_overflow <= accumulator_overflow | addition_overflow;
    end
  end

  // Cold nibbles clock only through their stage ICG: the gated edge arrives
  // exactly on clear/load or when a carry/borrow event reaches the stage.
  always @(posedge stage_2_gclk or negedge rst_n) begin
    if (!rst_n) begin
      stage_2 <= 4'b0;
    end else if (clear) begin
      stage_2 <= 4'b0;
    end else if (load) begin
      stage_2 <= load_value[11:8];
    end else if (accumulate && stage_update_event[2]) begin
      stage_2 <= next_stage_2;
    end
  end

  always @(posedge stage_3_gclk or negedge rst_n) begin
    if (!rst_n) begin
      stage_3 <= 4'b0;
    end else if (clear) begin
      stage_3 <= 4'b0;
    end else if (load) begin
      stage_3 <= load_value[15:12];
    end else if (accumulate && stage_update_event[3]) begin
      stage_3 <= next_stage_3;
    end
  end

  always @(posedge stage_4_gclk or negedge rst_n) begin
    if (!rst_n) begin
      stage_4 <= 4'b0;
    end else if (clear) begin
      stage_4 <= 4'b0;
    end else if (load) begin
      stage_4 <= load_value[19:16];
    end else if (accumulate && stage_update_event[4]) begin
      stage_4 <= next_stage_4;
    end
  end

endmodule

`default_nettype wire
