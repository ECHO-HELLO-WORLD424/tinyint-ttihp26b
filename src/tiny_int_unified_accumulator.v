/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Unified single-bank 20-bit accumulator built from five independently
// enabled 4-bit stage registers. One physical bank serves every architecture
// mode; the latched accumulator_mode selects only the update policy:
//   2'b00: boundary 20 (conventional). Every stage is an active adder stage
//          and all five stages commit on every accumulation edge.
//   2'b01: 8-bit active region,  2'b10: 12-bit active region,
//   2'b11: 16-bit active region (staged increment/decrement cold events).
//
// Bit-exactness contracts:
//   - Modes 2'b01/2'b10/2'b11 reproduce tiny_int_dynamic_accumulator exactly,
//     including operand isolation of the stage-2/3 adders, the cold-stage
//     increment/decrement event logic, carry_out semantics, and the sticky
//     accumulator_overflow.
//   - Mode 2'b00 reproduces tiny_int_accumulator exactly. The 20-bit addend
//     addition decomposes into a nibble ripple: stage k sums its addend
//     nibble plus the carry from below, so the concatenation of the five
//     nibble sums is full_addition[19:0] and addition_carry is the carry out
//     of bit 19, i.e. stage_4_addition[4]. This identity is purely an
//     unsigned-addition fact about the bit patterns, so it holds for
//     sign-extended addends as well and addition_overflow
//     (= signed_mode ? signed_addition_overflow : addition_carry) matches the
//     conventional module in every case.
//
// The addend contract is the output of product_extender: an unsigned 8-bit
// value zero-extended to 20 bits, or a signed 8-bit value sign-extended to 20
// bits. Cold stages therefore see only an increment, decrement, or hold
// event. No combinational or ripple-generated clock is used.
module tiny_int_unified_accumulator (
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

  // The first eight bits are active in every mode, including boundary 20.
  wire [4:0] stage_0_addition =
      {1'b0, stage_0} + {1'b0, addend[3:0]};
  wire [4:0] stage_1_addition =
      {1'b0, stage_1} + {1'b0, addend[7:4]} + stage_0_addition[4];

  // Isolate the operands of optional active-region adders. In dynamic-8 the
  // stage-2 adder inputs are constant; in dynamic-8/12 the stage-3 inputs are
  // constant; in every dynamic mode the stage-4 adder inputs are constant.
  // All three adders are fully active in boundary-20 mode. Cold-stage event
  // logic below remains available in the staged modes.
  wire stage_2_active = accumulator_mode != 2'b01;
  wire stage_3_active = (accumulator_mode == 2'b11) ||
                        (accumulator_mode == 2'b00);
  wire stage_4_active = accumulator_mode == 2'b00;
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
  wire [3:0] stage_4_active_addend = stage_4_active ? addend[19:16] : 4'b0;
  wire       stage_4_active_carry = stage_4_active ?
                                              stage_3_addition[4] : 1'b0;
  wire [4:0] stage_4_addition =
      {1'b0, stage_4} + {1'b0, stage_4_active_addend} +
      stage_4_active_carry;

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
      2'b00: begin : boundary_20_next
        // Conventional mode is the dynamic engine with the active boundary
        // pushed to 20 bits: every stage adds its addend nibble plus the
        // ripple carry from below and every stage commits on the edge. The
        // carry out of bit 19 is exactly the top nibble adder's carry, which
        // equals the conventional bank's full_addition[20] for signed and
        // unsigned addends alike.
        next_stage_2          = stage_2_addition[3:0];
        next_stage_3          = stage_3_addition[3:0];
        next_stage_4          = stage_4_addition[3:0];
        stage_update_event    = 5'b11111;
        carry_out             = stage_4_addition[4];
      end

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
        // 2'b11 is the legal dynamic-16 mode.
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

  // Clear/load intentionally write all five nibbles. During normal operation
  // the explicit enables allow synthesis to infer independently enabled state.
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      stage_0             <= 4'b0;
      stage_1             <= 4'b0;
      stage_2             <= 4'b0;
      stage_3             <= 4'b0;
      stage_4             <= 4'b0;
      accumulator_overflow <= 1'b0;
    end else if (clear) begin
      stage_0             <= 4'b0;
      stage_1             <= 4'b0;
      stage_2             <= 4'b0;
      stage_3             <= 4'b0;
      stage_4             <= 4'b0;
      accumulator_overflow <= 1'b0;
    end else if (load) begin
      stage_0             <= load_value[3:0];
      stage_1             <= load_value[7:4];
      stage_2             <= load_value[11:8];
      stage_3             <= load_value[15:12];
      stage_4             <= load_value[19:16];
      accumulator_overflow <= 1'b0;
    end else if (accumulate) begin
      stage_0 <= next_stage_0;
      stage_1 <= next_stage_1;
      if (stage_update_event[2]) begin
        stage_2 <= next_stage_2;
      end
      if (stage_update_event[3]) begin
        stage_3 <= next_stage_3;
      end
      if (stage_update_event[4]) begin
        stage_4 <= next_stage_4;
      end
      accumulator_overflow <= accumulator_overflow | addition_overflow;
    end
  end

endmodule

`default_nettype wire
