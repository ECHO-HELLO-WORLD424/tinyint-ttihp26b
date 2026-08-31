/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Thin Tiny Tapeout pin adapter. Command side effects remain centralized in
// tiny_int_core; this module only translates physical pins to a request.
module tiny_int_protocol (
    input  wire [7:0] ui_in,
    input  wire [4:0] uio_in,
    input  wire       core_ready,
    input  wire       response_valid,
    input  wire       busy,

    output wire       request_valid,
    output wire [2:0] request_command,
    output wire [7:0] request_data,
    output wire       request_signed_mode,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe
);

  assign request_valid       = uio_in[0];
  assign request_command     = uio_in[3:1];
  assign request_data        = ui_in;
  assign request_signed_mode = uio_in[4];

  assign uio_out = {busy, response_valid, core_ready, 5'b00000};
  assign uio_oe  = 8'b11100000;

endmodule

`default_nettype wire
