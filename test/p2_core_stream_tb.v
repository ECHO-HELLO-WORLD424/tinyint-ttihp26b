/*
 * Copyright (c) 2026 ECHO-HELLO-WORLD424
 * SPDX-License-Identifier: Apache-2.0
 */

`timescale 1ns / 1ps
`default_nettype none

// Core-level equivalence stream driver for the ICG clock-gating proposal
// (two-compilation log-diff pattern). The same testbench is compiled twice:
//   * with +DREF_CORE: instantiates tiny_int_core_ref, the frozen baseline
//     core in test/p2_ref/ (instantiating the baseline accumulator leaves);
//   * without: instantiates the modified tiny_int_core (ICG banks).
// Every cycle it writes all core observables to the file named by +OUT=<file>.
// The equivalence check is a byte-identical diff of the two logs, performed
// by test/run_p2_diff.sh.
//
// Scenario: all four modes x the mixed/unsigned/const1/zero workloads with
// CLEAR/READ/FINISH interleavings, post-done and reserved command rejections,
// and an async reset asserted while the clock is frozen (gates closed).

`define P2_LOG_FMT "%0d %b %b %h %b %b %h %b %h %b %h %b %h %b %b"

module p2_core_stream_tb;

  localparam [2:0] COMMAND_FINISH   = 3'b000;
  localparam [2:0] COMMAND_CLEAR    = 3'b001;
  localparam [2:0] COMMAND_MAC      = 3'b010;
  localparam [2:0] COMMAND_MAC_LAST = 3'b011;
  localparam [2:0] COMMAND_READ     = 3'b100;

  reg clk = 1'b0;
  reg clk_en = 1'b1;
  reg rst_n = 1'b1;  // the initial block creates the asynchronous negedge
                     // the FF resets need.

  reg        request_valid = 1'b0;
  reg [2:0]  request_command = 3'b000;
  reg [7:0]  request_data = 8'h00;
  reg        request_signed_mode = 1'b0;
  reg        request_from_bist = 1'b0;

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

`ifdef REF_CORE
  tiny_int_core_ref dut (
`else
  tiny_int_core dut (
`endif
      .clk                 (clk),
      .rst_n               (rst_n),
      .request_valid       (request_valid),
      .request_ready       (request_ready),
      .request_command     (request_command),
      .request_data        (request_data),
      .request_signed_mode (request_signed_mode),
      .request_from_bist   (request_from_bist),
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

  always #10 clk = clk_en ? ~clk : clk;

  integer flog = 0;
  integer cycle = 0;
  integer x_events = 0;
  reg [1023:1] log_path;

  // X observability guard: any unknown reaching a core observable is a bug
  // even if both compilations reproduced it identically.
  task x_watch;
    begin
      if ((^accumulator_value === 1'bx) ||
          (accumulator_overflow === 1'bx) ||
          (^response_data === 1'bx) ||
          (response_valid === 1'bx) ||
          (^pair_count === 1'bx) ||
          (done === 1'bx) ||
          (^last_product === 1'bx) ||
          (count_overflow === 1'bx) ||
          (protocol_error === 1'bx)) begin
        x_events = x_events + 1;
        if (x_events < 20) begin
          $display("X EVENT at cycle %0d: av=%h ovf=%b rd=%h rv=%b pc=%h dn=%b lp=%h co=%b pe=%b",
                   cycle, accumulator_value, accumulator_overflow,
                   response_data, response_valid, pair_count, done,
                   last_product, count_overflow, protocol_error);
        end
      end
    end
  endtask

  task log_now;
    input       rv;
    input [2:0] rc;
    input [7:0] rd;
    input       rsm;
    begin
      #1;
      $fdisplay(flog, `P2_LOG_FMT,
                cycle, rst_n, rv, rc, rd, rsm,
                accumulator_value, accumulator_overflow,
                response_data, response_valid,
                pair_count, done, last_product,
                count_overflow, protocol_error);
      x_watch;
      cycle = cycle + 1;
    end
  endtask

  task drive_cycle;
    input       rv;
    input [2:0] rc;
    input [7:0] rd;
    input       rsm;
    begin
      @(negedge clk);
      request_valid       <= rv;
      request_command     <= rc;
      request_data        <= rd;
      request_signed_mode <= rsm;
      request_from_bist   <= 1'b0;
      log_now(rv, rc, rd, rsm);
      @(posedge clk);
    end
  endtask

  task do_idle;
    begin
      drive_cycle(1'b0, 3'b000, 8'h00, 1'b0);
    end
  endtask

  task do_clear;
    input [1:0] mode;
    input       zs;
    input       sm;
    begin
      drive_cycle(1'b1, COMMAND_CLEAR, {5'b00000, zs, mode}, sm);
    end
  endtask

  task do_mac;
    input [7:0] d;
    input       last;
    input       sm;
    begin
      drive_cycle(1'b1, last ? COMMAND_MAC_LAST : COMMAND_MAC, d, sm);
    end
  endtask

  task do_read;
    input [2:0] sel;
    begin
      drive_cycle(1'b1, COMMAND_READ, {5'b00000, sel}, 1'b0);
    end
  endtask

  task do_finish;
    begin
      drive_cycle(1'b1, COMMAND_FINISH, 8'h00, 1'b0);
    end
  endtask

  task do_reserved;
    input [2:0] cmd;
    begin
      drive_cycle(1'b1, cmd, 8'h00, 1'b0);
    end
  endtask

  // The 8192-MAC mixed stream: four quarters with distinct data profiles
  // (identical to test/p2_acc_equiv_tb.v).
  function [7:0] mixed_data;
    input integer i;
    input [15:0] lfsr;
    begin
      if (i < 2048)       mixed_data = {lfsr[7:4], lfsr[3:0]};
      else if (i < 4096)  mixed_data = ((i & 3) == 0) ? {i[3:0], i[7:4]}
                                                      : 8'h00;
      else if (i < 6144)  mixed_data = i[0] ? 8'hf1 : 8'h71;
      else                mixed_data = {i[7:4], i[3:0]};
    end
  endfunction

  // One transaction cell: CLEAR(mode config), MAC stream with interleaved
  // READs, a mid-stream FINISH + rejections + re-CLEAR, terminating MAC_LAST,
  // post-done rejections, a full READ burst and reserved commands.
  task run_cell;
    input [1:0] mode;
    input       zs;
    input       sm;
    input [1:0] wl;      // 0: mixed, 1: 8'hff unsigned, 2: 8'h11 signed,
                         // 3: 8'h00 zero (zero-skip)
    integer i;
    integer sel;
    reg [7:0] d;
    reg [15:0] lfsr;
    begin
      lfsr = 16'h1ace;
      do_clear(mode, zs, sm);
      for (i = 0; i < 8192; i = i + 1) begin
        case (wl)
          1: d = 8'hff;
          2: d = 8'h11;
          3: d = 8'h00;
          default: begin
            d = mixed_data(i, lfsr);
            if (i < 2048) begin
              lfsr = {lfsr[14:0],
                      lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
            end
          end
        endcase
        do_mac(d, 1'b0, sm);
        if ((i % 997) == 996) begin
          do_read(i[2:0]);
        end
        if ((i % 1639) == 1638) begin
          do_read(3'b111);  // default selector returns 8'h42
        end
        // Mid-stream FINISH interleave: half the cells terminate early, get
        // post-done rejections, then re-CLEAR and keep streaming.
        if ((i == 4096) && (mode != 2'b01) && (wl == 0)) begin
          do_finish;
          do_read(3'b100);   // status byte shows done=1
          do_mac(8'h77, 1'b1, sm);  // rejected: done
          do_finish;                // rejected: done
          do_clear(mode, zs, sm);
        end
      end
      do_mac(d, 1'b1, sm);
      // Post-done rejections, then a full READ burst over every selector.
      do_mac(8'haa, 1'b0, sm);
      do_finish;
      do_read(3'b100);
      for (sel = 0; sel <= 7; sel = sel + 1) begin
        do_read(sel[2:0]);
      end
      // Reserved commands latch protocol_error; the next CLEAR clears it.
      do_reserved(3'b101);
      do_reserved(3'b110);
      do_reserved(3'b111);
      do_read(3'b100);
      repeat (3) do_idle;
    end
  endtask

  // Async reset reaches the FFs without the clock: freeze the clock (so the
  // bank gates never open), assert rst_n, and log the collapse to zero
  // before the clock is released.
  task async_reset_test;
    integer i;
    reg [7:0] d;
    begin
      repeat (2) do_idle;
      @(negedge clk);
      request_valid       <= 1'b0;
      request_command     <= 3'b000;
      request_data        <= 8'h00;
      request_signed_mode <= 1'b0;
      request_from_bist   <= 1'b0;
      clk_en <= 1'b0;   // freeze the clock low: no edges of any kind
      #2;
      log_now(1'b0, 3'b000, 8'h00, 1'b0);
      rst_n <= 1'b0;    // async reset, gates closed, no clock edges
      #1;
      log_now(1'b0, 3'b000, 8'h00, 1'b0);
      #10;
      log_now(1'b0, 3'b000, 8'h00, 1'b0);
      rst_n <= 1'b1;
      #1;
      log_now(1'b0, 3'b000, 8'h00, 1'b0);
      #2;
      clk_en <= 1'b1;
      // Short recovery transaction proves identical post-reset behavior.
      do_clear(2'b11, 1'b0, 1'b1);
      for (i = 0; i < 64; i = i + 1) begin
        d = mixed_data(i, 16'h1ace);
        do_mac(d, 1'b0, 1'b1);
      end
      do_mac(8'h21, 1'b1, 1'b1);
      do_finish;
      do_read(3'b000);
      do_read(3'b100);
      repeat (2) do_idle;
    end
  endtask

  integer mi;
  integer wi;
  reg zs;
  reg sm;

  initial begin
    if (!$value$plusargs("OUT=%s", log_path)) begin
      log_path = "p2_core_stream.log";
    end
    flog = $fopen(log_path, "w");
    if (flog == 0) begin
      $display("ERROR: cannot open log file %0s", log_path);
      $fatal(1, "p2_core_stream_tb log open failed");
    end

    // Asynchronous reset entry: a real 1 -> 0 negedge at time zero.
    rst_n = 1'b0;
    repeat (3) begin
      @(negedge clk);
      request_valid       <= 1'b0;
      request_command     <= 3'b000;
      request_data        <= 8'h00;
      request_signed_mode <= 1'b0;
      log_now(1'b0, 3'b000, 8'h00, 1'b0);
      @(posedge clk);
    end
    rst_n = 1'b1;
    repeat (2) do_idle;

    // Four modes x four workloads; signedness and zero-skip vary per cell.
    for (mi = 0; mi <= 3; mi = mi + 1) begin
      for (wi = 0; wi <= 3; wi = wi + 1) begin
        zs = (wi == 3) ? 1'b1 : ((wi == 0) ? mi[0] : 1'b0);
        sm = (wi == 2) ? 1'b1 : ((wi == 1) ? 1'b0 : mi[1]);
        run_cell(mi[1:0], zs, sm, wi[1:0]);
      end
    end

    async_reset_test;

    $fclose(flog);
    if (x_events != 0) begin
      $display("FAIL: p2_core_stream_tb saw %0d X events on core observables",
               x_events);
      $fatal(1, "p2_core_stream_tb X events");
    end
    $display("STREAM_DONE: p2_core_stream_tb wrote %0d cycles to %0s",
             cycle, log_path);
    $finish;
  end

endmodule

`default_nettype wire
