/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

module tt_um_echo_hello_world424_tinyint (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high)
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,
    input  wire       rst_n
);

  wire       external_request_valid;
  wire       core_request_ready;
  wire [2:0] external_request_command;
  wire [7:0] external_request_data;
  wire       external_request_signed_mode;
  wire       latched_signed_mode;
  wire [19:0] extended_product;
  wire [19:0] accumulator_value;
  wire [7:0] response_data;
  wire       response_valid;
  wire busy           = 1'b0;
  wire [7:0] pair_count;
  wire       done;
  wire [7:0] last_product;
  wire       accumulator_overflow;
  wire       count_overflow;
  wire       protocol_error;
  wire [7:0] multiplier_product;

  tiny_int_protocol protocol (
      .ui_in               (ui_in),
      .uio_in              (uio_in[4:0]),
      .core_ready          (core_request_ready),
      .response_valid      (response_valid),
      .busy                (busy),
      .request_valid       (external_request_valid),
      .request_command     (external_request_command),
      .request_data        (external_request_data),
      .request_signed_mode (external_request_signed_mode),
      .uio_out             (uio_out),
      .uio_oe              (uio_oe)
  );

  tiny_int_core core (
      .clk                 (clk),
      .rst_n               (rst_n),
      .request_valid       (external_request_valid),
      .request_ready       (core_request_ready),
      .request_command     (external_request_command),
      .request_data        (external_request_data),
      .request_signed_mode (external_request_signed_mode),
      .request_from_bist   (1'b0),
      .multiplier_product  (multiplier_product),
      .extended_product    (extended_product),
      .accumulator_value   (accumulator_value),
      .latched_signed_mode (latched_signed_mode),
      .response_data       (response_data),
      .response_valid      (response_valid),
      .pair_count          (pair_count),
      .done                (done),
      .last_product        (last_product),
      .accumulator_overflow(accumulator_overflow),
      .count_overflow      (count_overflow),
      .protocol_error      (protocol_error)
  );

  assign uo_out = response_data;

  // Prevent warnings for inputs/state that are intentionally not exposed on
  // dedicated pins. All are available through registered READ selectors.
  wire _unused = &{ena, uio_in[7:5], latched_signed_mode,
                   multiplier_product, extended_product, accumulator_value,
                   pair_count, done, last_product, accumulator_overflow,
                   count_overflow, protocol_error, 1'b0};

endmodule

`default_nettype wire
