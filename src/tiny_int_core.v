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

  // There is no multi-cycle operation in the minimum engine. The later BIST
  // arbiter may gate this ready signal while it owns the core request port.
  assign request_ready = rst_n;

  wire request_accepted = request_valid && request_ready;
  wire external_request_accepted = request_accepted && !request_from_bist;
  wire clear_accepted = external_request_accepted &&
                        (request_command == COMMAND_CLEAR);
  wire mac_command = (request_command == COMMAND_MAC) ||
                     (request_command == COMMAND_MAC_LAST);
  wire mac_accepted = request_accepted && mac_command && !done;
  wire mac_last_accepted = mac_accepted &&
                           (request_command == COMMAND_MAC_LAST);
  wire finish_accepted = external_request_accepted &&
                         (request_command == COMMAND_FINISH) && !done;
  wire read_accepted = external_request_accepted &&
                       (request_command == COMMAND_READ);
  wire completed_command_rejected = external_request_accepted && done &&
      ((request_command == COMMAND_FINISH) || mac_command);

  // Only an accepted external CLEAR samples the live mode pin. Normal MACs
  // always use this register, so live pin changes cannot alter a transaction.
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      signed_mode_register <= 1'b0;
    end else if (clear_accepted) begin
      signed_mode_register <= request_signed_mode;
    end
  end

  assign latched_signed_mode = signed_mode_register;

  // Internal BIST requests retain a per-vector mode input without changing the
  // externally latched mode. BIST generation itself is a later milestone.
  wire active_signed_mode = request_from_bist ? request_signed_mode
                                               : signed_mode_register;

  int4_multiplier multiplier_core (
      .multiplicand(request_data[3:0]),
      .multiplier  (request_data[7:4]),
      .signed_mode (active_signed_mode),
      .product     (multiplier_product)
  );

  product_extender product_extension (
      .product         (multiplier_product),
      .signed_mode     (active_signed_mode),
      .extended_product(extended_product)
  );

  wire [19:0] accumulator_addition_result;
  wire accumulator_addition_carry;
  wire accumulator_addition_overflow;

  tiny_int_accumulator accumulator (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear_accepted),
      .load                (1'b0),
      .accumulate          (mac_accepted),
      .signed_mode         (active_signed_mode),
      .load_value          (20'b0),
      .addend              (extended_product),
      .accumulator_value   (accumulator_value),
      .addition_result     (accumulator_addition_result),
      .addition_carry      (accumulator_addition_carry),
      .addition_overflow   (accumulator_addition_overflow),
      .accumulator_overflow(accumulator_overflow)
  );

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

      if (completed_command_rejected) begin
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
      default: selected_response_data = 8'b0;
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
                                      accumulator_addition_overflow, 1'b0};

endmodule

`default_nettype wire
