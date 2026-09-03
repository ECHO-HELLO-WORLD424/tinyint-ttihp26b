/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// State-owning command core for the streaming INT4 dot-product engine.
// The physical Tiny Tapeout protocol is deliberately kept outside this module.
//
// P3 variant: the conventional bank and the dynamic-8 bank are replaced by a
// single event-scheduled maintenance-domain accumulator
// (tiny_int_event_accumulator). The accumulator_mode register is still
// latched on CLEAR and reported through the configuration selector, but the
// update policy is mode-independent: the maintenance engine IS the general
// update policy and the mode exists for protocol compatibility only.
//
// Documented protocol deviation (the only one): a READ response is emitted
// two cycles after acceptance instead of one. At the acceptance edge the
// core forces the maintenance engine to canonicalize (flush); the response
// byte is captured one cycle later from the committed canonical state.
// Response DATA is bit-identical to the previous core for every selector and
// every command stream: no other command can be accepted in the READ
// acceptance cycle, and later commands only commit on edges after the
// capture. MAC acceptance is never stalled or dropped by a flush.
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

  // Operand isolation keeps the accumulator adder inputs constant while no
  // MAC is committed. This is synchronous data gating, not clock gating.
  wire [19:0] accumulator_addend = accumulator_write_enable ?
                                   extended_product : 20'b0;

  wire [19:0] event_accumulator_value;
  wire [19:0] event_canonical_value;
  wire        event_canonical_valid;
  wire [4:0]  event_stage_write_enable;
  wire        event_cold_write_active;

  // A READ forces the maintenance engine to canonicalize at the acceptance
  // edge so the response can be captured from committed state one cycle
  // later. MACs keep flowing during the flush.
  wire read_flush = read_accepted && !event_canonical_valid;

  tiny_int_event_accumulator event_accumulator (
      .clk                 (clk),
      .rst_n               (rst_n),
      .clear               (clear_accepted),
      .load                (1'b0),
      .accumulate          (accumulator_write_enable),
      .signed_mode         (signed_mode_register),
      .load_value          (20'b0),
      .addend              (accumulator_addend),
      .flush               (read_flush),
      .accumulator_value   (event_accumulator_value),
      .canonical_value     (event_canonical_value),
      .canonical_valid     (event_canonical_valid),
      .accumulator_overflow(accumulator_overflow),
      .stage_write_enable  (event_stage_write_enable),
      .cold_write_active   (event_cold_write_active)
  );

  // The architectural output carries the canonical value (the correction
  // chain is input-static between cold events); the stored bank alone may be
  // stale between maintenance ticks.
  assign accumulator_value = event_canonical_value;

  // READ responses are pipelined: acceptance at cycle T latches the byte
  // selector, the canonicalized bank is sampled during T+1, and
  // response_valid rises during T+2. The uniform latency keeps back-to-back
  // READs collision-free at one response per cycle.
  reg [1:0] read_response_pipe;
  reg [2:0] read_selector_register;

  reg [7:0] selected_response_data;
  always @(*) begin
    case (read_selector_register)
      3'b000: selected_response_data = event_accumulator_value[7:0];
      3'b001: selected_response_data = event_accumulator_value[15:8];
      3'b010: selected_response_data = {4'b0000,
                                        event_accumulator_value[19:16]};
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
      read_response_pipe     <= 2'b00;
      read_selector_register <= 3'b0;
      response_data          <= 8'b0;
      response_valid         <= 1'b0;
    end else begin
      read_response_pipe <= {read_response_pipe[0], read_accepted};
      if (read_accepted) begin
        read_selector_register <= request_data[2:0];
      end
      // read_pipe[0] is high the cycle after acceptance; the response byte
      // is captured from the canonicalized bank on the following edge and
      // response_valid rises with it (two cycles after acceptance).
      response_valid <= read_response_pipe[0];
      if (read_response_pipe[0]) begin
        response_data <= selected_response_data;
      end
    end
  end

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

  // Retain these useful observability points for RTL verification.
  wire _unused_accumulator_status = &{event_stage_write_enable,
                                      event_cold_write_active,
                                      event_accumulator_value[19:0],
                                      request_from_bist, 1'b0};

endmodule

`default_nettype wire
