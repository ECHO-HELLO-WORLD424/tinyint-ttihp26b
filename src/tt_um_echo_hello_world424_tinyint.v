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

  // These response/BIST signals are connected now so their physical pin
  // behavior is fixed before the response and BIST controllers are added.
  wire response_valid = 1'b0;
  wire busy           = 1'b0;

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
      .multiplier_product  (uo_out),
      .extended_product    (extended_product),
      .accumulator_value   (accumulator_value),
      .latched_signed_mode (latched_signed_mode)
  );

  // Prevent warnings for inputs/state reserved for later implementation
  // steps. The current top-level baseline still exposes the raw multiplier
  // result until the registered response interface is implemented.
  wire _unused = &{ena, uio_in[7:5], latched_signed_mode,
                   extended_product, accumulator_value, 1'b0};

endmodule

`default_nettype wire
