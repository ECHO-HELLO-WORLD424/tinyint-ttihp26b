/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// State-owning command core for the streaming INT4 dot-product engine.
// The physical Tiny Tapeout protocol is deliberately kept outside this module.
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
  wire conventional_selected = accumulator_mode_register == 2'b00;
  wire conventional_accumulate = accumulator_write_enable &&
                                 conventional_selected;
  wire dynamic_accumulate = accumulator_write_enable &&
                            !conventional_selected;

  // Operand isolation keeps each unselected adder input constant as well as
  // disabling its state write. This is synchronous data gating, not clock
  // gating; clk reaches every register through the normal CTS network.
  wire [19:0] conventional_addend = conventional_accumulate ?
                                    extended_product : 20'b0;
  wire [19:0] dynamic_addend = dynamic_accumulate ?
                               extended_product : 20'b0;

  wire [19:0] conventional_accumulator_value;
  wire [19:0] conventional_addition_result;
  wire conventional_addition_carry;
  wire conventional_addition_overflow;
  wire conventional_accumulator_overflow;

  tiny_int_accumulator conventional_accumulator (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear_accepted),
      .load                (1'b0),
      .accumulate          (conventional_accumulate),
      .signed_mode         (signed_mode_register),
      .load_value          (20'b0),
      .addend              (conventional_addend),
      .accumulator_value   (conventional_accumulator_value),
      .addition_result     (conventional_addition_result),
      .addition_carry      (conventional_addition_carry),
      .addition_overflow   (conventional_addition_overflow),
      .accumulator_overflow(conventional_accumulator_overflow)
  );

  wire [19:0] dynamic_accumulator_value;
  wire [19:0] dynamic_addition_result;
  wire dynamic_addition_carry;
  wire dynamic_addition_overflow;
  wire dynamic_accumulator_overflow;
  wire [4:0] dynamic_stage_write_enable;

  // The clock-gated dynamic accumulator is a power-study prototype; the tapeout
  // regression keeps the data-gated leaf by default. Synthesis selects the
  // clock-gated variant with VERILOG_DEFINES=CLKGATE_ACCUMULATOR.
`ifdef CLKGATE_ACCUMULATOR
  tiny_int_dynamic_accumulator_clkgate dynamic_accumulator (
`else
  tiny_int_dynamic_accumulator dynamic_accumulator (
`endif
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear_accepted),
      .load                (1'b0),
      .accumulate          (dynamic_accumulate),
      .signed_mode         (signed_mode_register),
      .accumulator_mode    (accumulator_mode_register),
      .load_value          (20'b0),
      .addend              (dynamic_addend),
      .accumulator_value   (dynamic_accumulator_value),
      .addition_result     (dynamic_addition_result),
      .addition_carry      (dynamic_addition_carry),
      .addition_overflow   (dynamic_addition_overflow),
      .accumulator_overflow(dynamic_accumulator_overflow),
      .stage_write_enable  (dynamic_stage_write_enable)
  );

  assign accumulator_value = conventional_selected ?
                             conventional_accumulator_value :
                             dynamic_accumulator_value;
  assign accumulator_overflow = conventional_selected ?
                                conventional_accumulator_overflow :
                                dynamic_accumulator_overflow;

  // Preserve the selected arithmetic observation points used by RTL tests.
  wire [19:0] accumulator_addition_result = conventional_selected ?
      conventional_addition_result : dynamic_addition_result;
  wire accumulator_addition_carry = conventional_selected ?
      conventional_addition_carry : dynamic_addition_carry;
  wire accumulator_addition_overflow = conventional_selected ?
      conventional_addition_overflow : dynamic_addition_overflow;

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
      3'b110: selected_response_data = {4'b0000, zero_skip_register,
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
                                      conventional_addition_carry,
                                      conventional_addition_overflow,
                                      dynamic_addition_carry,
                                      dynamic_addition_overflow,
                                      dynamic_stage_write_enable,
                                      request_from_bist, 1'b0};

endmodule

`default_nettype wire
