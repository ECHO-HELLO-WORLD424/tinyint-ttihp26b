/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 *
 * Standalone trace cell for the adaptive-boundary activity monitor.
 *
 * Drives tiny_int_core with a random accepted-MAC stream (CLEAR and MAC
 * commands only, so every MAC is accepted) and dumps one trace line per
 * accepted command:
 *
 *   C <mode>                            accepted CLEAR with payload mode
 *   M <written> <extbit> <boundary>     accepted MAC: write enable, the
 *                                       extended product's bit 19, and the
 *                                       effective boundary after that edge
 *
 * The companion script p4_monitor_replay.py replays these lines through the
 * Python BoundaryMonitor mirrors and asserts the mirror boundary equals the
 * RTL boundary at every accepted MAC.
 *
 * Run: iverilog -g2012 -o p4_monitor_trace.vvp p4_monitor_trace_tb.v \
 *        ../src/tiny_int_core.v ../src/tiny_int_unified_accumulator.v \
 *        ../src/int4_multiplier.v ../src/product_extender.v \
 *        ../src/tiny_int_accumulator.v
 *      vvp p4_monitor_trace.vvp
 *      python3 p4_monitor_replay.py p4_monitor_trace.log
 */

`timescale 1ns / 1ps
`default_nettype none

module p4_monitor_trace_tb;

  reg         clk;
  reg         rst_n;
  reg         req_valid;
  reg [2:0]   req_command;
  reg [7:0]   req_data;
  reg         req_signed_mode;
  wire        request_ready;

  wire [7:0]  multiplier_product;
  wire [19:0] extended_product;
  wire [19:0] accumulator_value;
  wire        latched_signed_mode;
  wire [7:0]  response_data;
  wire        response_valid;
  wire [7:0]  pair_count;
  wire        done;
  wire [7:0]  last_product;
  wire        accumulator_overflow;
  wire        count_overflow;
  wire        protocol_error;

  tiny_int_core dut (
      .clk                  (clk),
      .rst_n                (rst_n),
      .request_valid        (req_valid),
      .request_ready        (request_ready),
      .request_command      (req_command),
      .request_data         (req_data),
      .request_signed_mode  (req_signed_mode),
      .request_from_bist    (1'b0),
      .multiplier_product   (multiplier_product),
      .extended_product     (extended_product),
      .accumulator_value    (accumulator_value),
      .latched_signed_mode  (latched_signed_mode),
      .response_data        (response_data),
      .response_valid       (response_valid),
      .pair_count           (pair_count),
      .done                 (done),
      .last_product         (last_product),
      .accumulator_overflow (accumulator_overflow),
      .count_overflow       (count_overflow),
      .protocol_error       (protocol_error)
  );

  always #5 clk = ~clk;

  integer fh;
  integer seed = 32'h5EEDFACE;
  integer i;
  integer clears;
  integer macs;
  reg [7:0] data;
  reg [1023:0] seed_arg;

  // One command per clock. Inputs are held across the edge, so the #1
  // samples below observe exactly the pre-edge state the edge consumed.
  task issue_cmd;
    input [2:0] cmd;
    input [7:0] payload;
    input       signed_mode;
    begin
      req_valid       = 1'b1;
      req_command     = cmd;
      req_data        = payload;
      req_signed_mode = signed_mode;
      @(posedge clk);
      #1;
      if (cmd == 3'b001) begin
        clears = clears + 1;
        $fdisplay(fh, "C %0d", payload[1:0]);
        if (dut.effective_boundary !== payload[1:0]) begin
          $display("FAIL t=%0t CLEAR: effective=%b expected=%b",
                   $time, dut.effective_boundary, payload[1:0]);
          $fatal(1);
        end
      end else begin
        macs = macs + 1;
        $fdisplay(fh, "M %0d %0d %0d",
                  dut.accumulator_write_enable,
                  dut.extended_product[19],
                  dut.effective_boundary);
      end
      req_valid = 1'b0;
      #2;
    end
  endtask

  initial begin
    if (!$value$plusargs("seed=%d", seed)) begin
      seed = 32'h5EEDFACE;
    end
    fh = $fopen("p4_monitor_trace.log", "w");
    clk             = 1'b0;
    rst_n           = 1'b0;
    req_valid       = 1'b0;
    req_command     = 3'b000;
    req_data        = 8'h00;
    req_signed_mode = 1'b0;
    clears          = 0;
    macs            = 0;
    repeat (2) @(posedge clk);
    #1 rst_n = 1'b1;
    #2;

    for (i = 0; i < 60000; i = i + 1) begin
      if (($random(seed) % 200) == 0) begin
        // Accepted CLEAR: random latched mode, zero skip, and signed mode.
        data[1:0] = $random(seed);
        data[2]   = $random(seed);
        data[3]   = 1'b0;
        data[7]   = $random(seed);
        issue_cmd(3'b001, data, data[7]);
      end else begin
        // Accepted MAC; a quarter of them are zero products so that
        // zero_skip exercises skipped (unwritten) MACs.
        if (($random(seed) % 4) == 0) begin
          data = 8'h00;
        end else begin
          data = $random(seed);
        end
        issue_cmd(3'b010, data, $random(seed) & 1);
      end
    end

    $fclose(fh);
    $display("TRACE-OK clears=%0d macs=%0d", clears, macs);
    $finish;
  end

endmodule

`default_nettype wire
