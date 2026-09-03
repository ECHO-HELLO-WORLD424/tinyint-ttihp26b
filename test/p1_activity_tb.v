/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Activity metrics for the unified single-bank proposal.
//
// Drives the W_MIXED stream (8192 signed MACs, zero-skip disabled) through
// the proposal core with the CLEAR mode payload selected by +MODE=0|1 and
// reports, per run:
//   - per-stage write-event counts, sampled from the core's
//     accumulator_stage_write_enable just before every rising edge, and
//   - per-nibble state toggle counts, comparing the registered accumulator
//     value between consecutive cycles (bits 0-3, 4-7, 8-11, 12-15, 16-19).
//
// The harness self-checks the expected write counts: with zero-skip disabled
// every one of the 8192 MACs accumulates, so the two active low stages are
// written every cycle in any mode, and in boundary-20 mode all five stages
// are written every cycle.
module p1_activity_tb;

  reg         clk;
  reg         rst_n;
  reg         request_valid;
  wire        request_ready;
  reg  [2:0]  request_command;
  reg  [7:0]  request_data;
  reg         request_signed_mode;

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
      .clk                 (clk),
      .rst_n               (rst_n),
      .request_valid       (request_valid),
      .request_ready       (request_ready),
      .request_command     (request_command),
      .request_data        (request_data),
      .request_signed_mode (request_signed_mode),
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

  initial clk = 1'b0;
  always #5 clk = ~clk;

  integer mode;
  integer i;
  integer bit_index;
  integer stage_writes [0:4];
  integer nibble_toggles [0:4];
  reg [19:0] previous_value;
  reg [4:0] sampled_we;
  reg [15:0] lfsr;
  reg [7:0] d;

  task drive_command;
    input [2:0] command;
    input [7:0] data;
    begin
      @(negedge clk);
      // The edge that just passed committed exactly one state transition.
      for (bit_index = 0; bit_index < 20; bit_index = bit_index + 1) begin
        if (accumulator_value[bit_index] != previous_value[bit_index]) begin
          nibble_toggles[bit_index / 4] = nibble_toggles[bit_index / 4] + 1;
        end
      end
      previous_value = accumulator_value;

      request_valid       = 1'b1;
      request_command     = command;
      request_data        = data;
      request_signed_mode = 1'b1;

      // Settle well before the rising edge, then record the write enables
      // the registers act on at that edge.
      #4;
      sampled_we = dut.accumulator_stage_write_enable;
      for (bit_index = 0; bit_index < 5; bit_index = bit_index + 1) begin
        if (sampled_we[bit_index]) begin
          stage_writes[bit_index] = stage_writes[bit_index] + 1;
        end
      end
    end
  endtask

  initial begin
    clk                 = 1'b0;
    rst_n               = 1'b0;
    request_valid       = 1'b0;
    request_command     = 3'b000;
    request_data        = 8'h00;
    request_signed_mode = 1'b1;
    previous_value      = 20'b0;

    if (!$value$plusargs("MODE=%d", mode)) mode = 0;
    if (mode < 0 || mode > 1) begin
      $fatal(1, "MODE must be 0 (boundary 20) or 1 (dynamic 8)");
    end
    for (i = 0; i < 5; i = i + 1) begin
      stage_writes[i]    = 0;
      nibble_toggles[i]  = 0;
    end

    repeat (3) @(negedge clk);
    rst_n = 1'b1;

    drive_command(3'b001, {1'b0, mode[1:0]});

    // W_MIXED: LFSR, 75%-zero sparse, alternating +/- carry/borrow, and
    // nibble-ramp quarters; signed mode constant, zero-skip disabled.
    lfsr = 16'h1ace;
    for (i = 0; i < 8192; i = i + 1) begin
      if (i < 2048) begin
        d = {lfsr[7:4], lfsr[3:0]};
        lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
      end else if (i < 4096) begin
        d = ((i & 3) == 0) ? {i[3:0], i[7:4]} : 8'h00;
      end else if (i < 6144) begin
        d = i[0] ? 8'hf1 : 8'h71;
      end else begin
        d = {i[7:4], i[3:0]};
      end
      drive_command(3'b010, d);
    end

    drive_command(3'b000, 8'h00);
    drive_command(3'b100, 8'h04);
    @(negedge clk);

    // Harness self-check: with zero-skip disabled every MAC accumulates, so
    // the two always-active low stages commit 8192 times in any mode, and
    // boundary-20 mode commits all five stages on every cycle.
    if (stage_writes[0] != 8192 || stage_writes[1] != 8192) begin
      $display("FAIL mode=%0d active-stage writes s0=%0d s1=%0d expected 8192",
               mode, stage_writes[0], stage_writes[1]);
      $fatal(1);
    end
    if (mode == 0 && (stage_writes[2] != 8192 || stage_writes[3] != 8192 ||
                      stage_writes[4] != 8192)) begin
      $display("FAIL mode=0 cold-stage writes s2=%0d s3=%0d s4=%0d expected 8192",
               stage_writes[2], stage_writes[3], stage_writes[4]);
      $fatal(1);
    end

    $display("ACTIVITY mode=%0d stream=W_MIXED macs=8192 signed=1 zero_skip=0",
             mode);
    $display("ACTIVITY mode=%0d stage_write_events s0=%0d s1=%0d s2=%0d s3=%0d s4=%0d",
             mode, stage_writes[0], stage_writes[1], stage_writes[2],
             stage_writes[3], stage_writes[4]);
    $display("ACTIVITY mode=%0d nibble_bit_toggles n0=%0d n1=%0d n2=%0d n3=%0d n4=%0d",
             mode, nibble_toggles[0], nibble_toggles[1], nibble_toggles[2],
             nibble_toggles[3], nibble_toggles[4]);
    $display("PASS p1_activity mode=%0d", mode);
    $finish;
  end

endmodule

`default_nettype wire
