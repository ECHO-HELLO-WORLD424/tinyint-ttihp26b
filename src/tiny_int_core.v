/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// State-owning command core for the streaming INT4 dot-product engine.
// The physical Tiny Tapeout protocol is deliberately kept outside this module.
//
// P4 adaptive-boundary proposal: the unified single-bank accumulator of the
// P1 proposal is retained, but the boundary the bank actually runs is chosen
// by an on-chip activity monitor instead of being pinned to the CLEAR payload.
// The monitor exploits the measured workload structure of this design:
//   - The energy the staged policy saves over the full 20-bit adder comes
//     from the redundant sign-extension bits of the addend, which toggle only
//     when consecutive signed products change sign. Measured post-layout
//     sweeps show the intermediate boundaries (12/16) are never the optimum:
//     dense unsigned streams make every staged policy lose to the full adder,
//     and sparse/unsigned streams leave the cold stages quasi-static anyway.
// Every 64 accepted MACs the monitor counts written MACs whose extended
// product flipped its top bit (the sign-extension region changed) and
// retunes between the only two policies that can be optimal:
//   - extension flips >= 16/64 (25%)  -> boundary 8 (staged policy),
//   - extension flips < 16/64         -> boundary 20 (full adder).
// A decision applies after it repeats in two consecutive windows. CLEAR
// reloads the latched mode as the initial effective boundary (so the latched
// 12/16 modes remain available as static choices). Because every boundary
// policy is bit-exact (identical stored value, identical true carry),
// retuning changes which adders evaluate, never the architecture state. The
// only observable change is READ selector 3'b110, whose former constant-zero
// upper nibble now reports {2'b00, effective_boundary}.
module tiny_int_core (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        request_valid,
    output wire        request_ready,
    input  wire [2:0]  request_command,
    input  wire [7:0]  request_data,
    input  wire        request_signed_mode,
    input  wire        request_from_bist,

    output wire [7:0]  multiplier_product,
    output wire [19:0] extended_product,
    output wire [19:0] accumulator_value,
    output wire        latched_signed_mode,
    output reg  [7:0]  response_data,
    output reg         response_valid,
    output reg  [7:0]  pair_count,
    output reg         done,
    output reg  [7:0]  last_product,
    output wire        accumulator_overflow,
    output reg         count_overflow,
    output reg         protocol_error
);

  localparam [2:0] COMMAND_FINISH   = 3'b000;
  localparam [2:0] COMMAND_CLEAR    = 3'b001;
  localparam [2:0] COMMAND_MAC      = 3'b010;
  localparam [2:0] COMMAND_MAC_LAST = 3'b011;
  localparam [2:0] COMMAND_READ     = 3'b100;

  reg signed_mode_register;
  reg [1:0] accumulator_mode_register;
  reg zero_skip_register;

  // There is no multi-cycle operation or response backpressure in this design.
  assign request_ready = rst_n;

  wire request_accepted = request_valid && request_ready;
  wire clear_accepted = request_accepted &&
                        (request_command == COMMAND_CLEAR);
  wire mac_command = (request_command == COMMAND_MAC) ||
                     (request_command == COMMAND_MAC_LAST);
  wire mac_accepted = request_accepted && mac_command && !done;
  wire mac_last_accepted = mac_accepted &&
                           (request_command == COMMAND_MAC_LAST);
  wire finish_accepted = request_accepted &&
                         (request_command == COMMAND_FINISH) && !done;
  wire read_accepted = request_accepted &&
                       (request_command == COMMAND_READ);
  wire completed_command_rejected = request_accepted && done &&
      ((request_command == COMMAND_FINISH) || mac_command);
  wire reserved_command_rejected = request_accepted &&
      (request_command >= 3'b101);

  // Only an accepted external CLEAR samples the live mode pin. Normal MACs
  // always use this register, so live pin changes cannot alter a transaction.
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      signed_mode_register <= 1'b0;
      accumulator_mode_register <= 2'b00;
      zero_skip_register <= 1'b0;
    end else if (clear_accepted) begin
      signed_mode_register <= request_signed_mode;
      accumulator_mode_register <= request_data[1:0];
      zero_skip_register <= request_data[2];
    end
  end

  assign latched_signed_mode = signed_mode_register;

  int4_multiplier multiplier_core (
      .multiplicand(request_data[3:0]),
      .multiplier  (request_data[7:4]),
      .signed_mode (signed_mode_register),
      .product     (multiplier_product)
  );

  product_extender product_extension (
      .product         (multiplier_product),
      .signed_mode     (signed_mode_register),
      .extended_product(extended_product)
  );

  wire product_is_zero = multiplier_product == 8'b0;
  wire accumulator_write_enable = mac_accepted &&
      (!zero_skip_register || !product_is_zero);

  // One shared addend path replaces the former per-bank gating pair: the
  // unified bank sees the extended product only on an enabled accumulation,
  // otherwise every adder operand is held constant.
  wire [19:0] accumulator_addend = accumulator_write_enable ?
                                   extended_product : 20'b0;

  wire [19:0] unified_accumulator_value;
  wire [19:0] unified_addition_result;
  wire unified_addition_carry;
  wire unified_addition_overflow;
  wire unified_accumulator_overflow;
  wire [4:0] accumulator_stage_write_enable;

  // Driven by the adaptive-boundary monitor below; forward-declared here so
  // the bank can be instantiated before the monitor's counters exist.
  reg [1:0] effective_boundary;

  tiny_int_unified_accumulator unified_accumulator (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear_accepted),
      .load                (1'b0),
      .accumulate          (accumulator_write_enable),
      .signed_mode         (signed_mode_register),
      .accumulator_mode    (effective_boundary),
      .load_value          (20'b0),
      .addend              (accumulator_addend),
      .accumulator_value   (unified_accumulator_value),
      .addition_result     (unified_addition_result),
      .addition_carry      (unified_addition_carry),
      .addition_overflow   (unified_addition_overflow),
      .accumulator_overflow(unified_accumulator_overflow),
      .stage_write_enable  (accumulator_stage_write_enable)
  );

  // ------------------------------------------------------------------
  // Adaptive-boundary activity monitor.
  //
  // Window statistics over 64 accepted MACs (written or zero-skipped):
  //   extension_event_count: written MACs whose extended product flipped
  //     its top bit, i.e. the sign-extension region changed. This is the
  //     event stream the staged boundary-8 policy saves over the full
  //     20-bit adder, and the only workload statistic that decides the
  //     optimal policy in the measured sweeps.
  // The counter cannot saturate: at most 64 events fit a 64-MAC window and
  // the counter is 7 bits wide.
  // ------------------------------------------------------------------
  reg [5:0] window_mac_count;
  reg [6:0] extension_event_count;
  reg       previous_extension_bit;
  reg [1:0] previous_window_decision;

  wire extension_flip = accumulator_write_enable &&
                        (extended_product[19] != previous_extension_bit);

  wire window_complete = mac_accepted && (window_mac_count == 6'd63);
  wire [1:0] window_decision =
      (extension_event_count >= 7'd16) ? 2'b01 : 2'b00;
  wire apply_window_decision = window_complete &&
      (window_decision == previous_window_decision);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      window_mac_count        <= 6'd0;
      extension_event_count   <= 7'd0;
      previous_extension_bit  <= 1'b0;
      effective_boundary      <= 2'b00;
      previous_window_decision <= 2'b00;
    end else if (clear_accepted) begin
      // A new transaction restarts the monitor at the latched mode.
      window_mac_count        <= 6'd0;
      extension_event_count   <= 7'd0;
      previous_extension_bit  <= 1'b0;
      effective_boundary      <= request_data[1:0];
      previous_window_decision <= request_data[1:0];
    end else begin
      if (accumulator_write_enable) begin
        previous_extension_bit <= extended_product[19];
        if (extension_flip) begin
          extension_event_count <= extension_event_count + 7'd1;
        end
      end

      if (window_complete) begin
        window_mac_count      <= 6'd0;
        extension_event_count <= 7'd0;
        previous_window_decision <= window_decision;
        if (apply_window_decision) begin
          effective_boundary <= window_decision;
        end
      end else if (mac_accepted) begin
        window_mac_count <= window_mac_count + 6'd1;
      end
    end
  end

  assign accumulator_value = unified_accumulator_value;
  assign accumulator_overflow = unified_accumulator_overflow;

  // Preserve the selected arithmetic observation points used by RTL tests.
  wire [19:0] accumulator_addition_result = unified_addition_result;
  wire accumulator_addition_carry = unified_addition_carry;
  wire accumulator_addition_overflow = unified_addition_overflow;

  // Transaction bookkeeping. The count saturates rather than wrapping, while
  // every accepted pair still reaches the accumulator after count overflow.
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pair_count     <= 8'b0;
      done           <= 1'b0;
      last_product   <= 8'b0;
      count_overflow <= 1'b0;
      protocol_error <= 1'b0;
    end else if (clear_accepted) begin
      pair_count     <= 8'b0;
      done           <= 1'b0;
      last_product   <= 8'b0;
      count_overflow <= 1'b0;
      protocol_error <= 1'b0;
    end else begin
      if (mac_accepted) begin
        last_product <= multiplier_product;
        if (pair_count == 8'hff) begin
          count_overflow <= 1'b1;
        end else begin
          pair_count <= pair_count + 1'b1;
        end
      end

      if (mac_last_accepted || finish_accepted) begin
        done <= 1'b1;
      end

      if (completed_command_rejected || reserved_command_rejected) begin
        protocol_error <= 1'b1;
      end
    end
  end

  // READ data is selected from architectural state as it exists at the
  // acceptance edge, then captured for the immediately following cycle.
  reg [7:0] selected_response_data;
  always @(*) begin
    case (request_data[2:0])
      3'b000: selected_response_data = accumulator_value[7:0];
      3'b001: selected_response_data = accumulator_value[15:8];
      3'b010: selected_response_data = {4'b0000, accumulator_value[19:16]};
      3'b011: selected_response_data = pair_count;
      3'b100: selected_response_data = {3'b000, protocol_error,
                                        count_overflow,
                                        accumulator_overflow,
                                        signed_mode_register, done};
      3'b101: selected_response_data = last_product;
      3'b110: selected_response_data = {2'b00, effective_boundary,
                                        zero_skip_register,
                                        accumulator_mode_register,
                                        signed_mode_register};
      default: selected_response_data = 8'h42;
    endcase
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      response_data  <= 8'b0;
      response_valid <= 1'b0;
    end else begin
      response_valid <= read_accepted;
      if (read_accepted) begin
        response_data <= selected_response_data;
      end
    end
  end

  // Retain these useful arithmetic observability points for RTL verification.
  wire _unused_accumulator_status = &{accumulator_addition_result,
                                      accumulator_addition_carry,
                                      accumulator_addition_overflow,
                                      accumulator_stage_write_enable,
                                      request_from_bist, 1'b0};

endmodule

`default_nettype wire
